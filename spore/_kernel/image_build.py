"""Build and maintain spore-kernel Docker images inside DinD."""

from __future__ import annotations

from docker.errors import DockerException

from spore._logger import logging
from spore._utils import kernel_runtime, repo_root

ALLOWED_PYTHON_VERSIONS = ("3.11", "3.12", "3.13")


def kernel_image_tag(python_version: str) -> str:
    return f"spore-kernel:{python_version}"


def package_specs(packages: list | None = None) -> str:
    """Space-separated pip specs for Dockerfile EXTRA_PACKAGES."""
    specs = []
    for pkg in packages if packages is not None else (kernel_runtime().get("packages") or []):
        name = (pkg.get("name") or "").strip()
        if not name:
            continue
        version = (pkg.get("version") or "").strip()
        specs.append(f"{name}=={version}" if version else name)
    return " ".join(specs)


def stop_all_kernel_containers(client) -> dict:
    """Force-stop and remove every per-session kernel container inside DinD."""
    stopped = 0
    removed = 0
    for container in client.containers.list(all=True):
        name = container.name or ""
        if not name.startswith("spore-kernel-"):
            continue
        try:
            if container.status == "running":
                container.stop(timeout=5)
                stopped += 1
            container.remove(force=True)
            removed += 1
        except DockerException as exc:
            logging.warning("Failed to stop/remove kernel container %s: %s", name, exc)
    return {"containers_stopped": stopped, "containers_removed": removed}


def cleanup_kernel_storage(client, keep_tags: set[str] | None = None) -> dict:
    """Remove dangling kernel images and any leftover per-session kernel containers."""
    keep_tags = keep_tags or set()
    container_stats = stop_all_kernel_containers(client)

    prune_images = client.images.prune(filters={"dangling": True})
    prune_containers = client.containers.prune()

    space = int(prune_images.get("SpaceReclaimed") or 0)
    space += int(prune_containers.get("SpaceReclaimed") or 0)
    deleted = prune_images.get("ImagesDeleted") or []

    return {
        "containers_stopped": container_stats["containers_stopped"],
        "containers_removed": container_stats["containers_removed"],
        "images_deleted": len(deleted),
        "space_reclaimed": space,
    }


def prepare_kernel_rebuild(client, tag: str) -> dict:
    """Stop kernels, remove the previous tagged image, and prune leftovers."""
    from spore._kernel.execution_queue import clear_all_queues
    from spore._kernel.store import destroy_all_kernels

    destroy_all_kernels()
    clear_all_queues(reason="Kernel rebuild")
    stop_all_kernel_containers(client)

    try:
        client.images.remove(tag, force=True)
    except DockerException as exc:
        if "No such image" not in str(exc) and "not found" not in str(exc).lower():
            logging.warning("Could not remove old kernel image %s: %s", tag, exc)

    prune_images = client.images.prune(filters={"dangling": True})
    prune_containers = client.containers.prune()
    space = int(prune_images.get("SpaceReclaimed") or 0)
    space += int(prune_containers.get("SpaceReclaimed") or 0)
    deleted = prune_images.get("ImagesDeleted") or []
    return {
        "images_deleted": len(deleted),
        "space_reclaimed": space,
    }


def iter_kernel_image_build(
    client,
    python_version: str,
    extra_packages: str | None = None,
):
    """Yield Docker build events, then a cleanup summary event."""
    if python_version not in ALLOWED_PYTHON_VERSIONS:
        raise ValueError(f"Unsupported Python version: {python_version}")

    tag = kernel_image_tag(python_version)
    packages = extra_packages if extra_packages is not None else package_specs()

    prep = prepare_kernel_rebuild(client, tag)
    if prep.get("images_deleted"):
        yield {
            "type": "cleanup",
            "content": (
                f"Prepared rebuild: removed {prep['images_deleted']} old image(s) "
                "and stopped kernel containers"
            ),
            "cleanup": prep,
        }

    for event in client.api.build(
        path=str(repo_root()),
        dockerfile="docker/Dockerfile.kernel",
        tag=tag,
        buildargs={
            "KERNEL_BASE_IMAGE": f"python:{python_version}-slim",
            "EXTRA_PACKAGES": packages,
        },
        pull=False,
        rm=True,
        forcerm=True,
        decode=True,
    ):
        yield event
        if "error" in event:
            raise DockerException(event["error"])

    post = cleanup_kernel_storage(client, keep_tags={tag})
    total_deleted = prep.get("images_deleted", 0) + post.get("images_deleted", 0)
    total_containers = post.get("containers_removed", 0)
    if post.get("images_deleted") or post.get("containers_removed"):
        yield {
            "type": "cleanup",
            "content": (
                f"Reclaimed storage: removed {post.get('images_deleted', 0)} leftover image(s), "
                f"{post.get('containers_removed', 0)} kernel container(s)"
            ),
            "cleanup": post,
        }
    elif total_deleted or total_containers:
        yield {
            "type": "cleanup",
            "content": (
                f"Rebuild complete: reclaimed {total_deleted} old image(s) and "
                f"{total_containers} kernel container(s) total"
            ),
        }


def build_kernel_image(
    client,
    python_version: str,
    extra_packages: str | None = None,
    *,
    on_event=None,
) -> str:
    """Build spore-kernel:<python_version> and prune superseded artifacts."""
    tag = kernel_image_tag(python_version)
    for event in iter_kernel_image_build(client, python_version, extra_packages):
        if on_event:
            on_event(event)
    return tag
