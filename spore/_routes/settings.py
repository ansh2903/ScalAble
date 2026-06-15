from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from flask import render_template, jsonify, request, redirect, url_for, flash, Response, stream_with_context

from spore._engine.model_manager import reset_engine
from spore._kernel.manager import get_docker_client
from spore._workspace.store import get_workspace_store
from spore._utils import (
    model_ls,
    load_settings,
    save_settings,
    merge_settings_section,
    kernel_runtime,
    security_runtime,
    data_runtime,
    repo_root,
    file_size_fmt,
)
from spore._config.settings import (
    PROVIDER_FIELDS,
    PROVIDER_BASE_URLS,
    URL_CONFIGURABLE_PROVIDERS,
)
from spore._routes.utils import generate_blueprint

from spore._logger import logging


settings_blueprint = generate_blueprint('settings')

ALLOWED_PYTHON_VERSIONS = ("3.11", "3.12", "3.13")


def _active_stream_names() -> set[str]:
    """Collect stream names referenced by any workspace catalog."""
    store = get_workspace_store()
    active: set[str] = set()
    for ws in store.list_workspaces():
        state = store.get_state(ws["id"])
        if not state:
            continue
        data = state.get("data") or {}
        relations = data.get("relations") or {}
        active.update(str(name) for name in relations.keys())
    return active


@settings_blueprint.route('/settings', methods=['GET', 'POST'])
def settings():
    settings_data = load_settings() or {}
    provider, model = settings_data.get("provider", None), settings_data.get("model", None)

    if request.method == "POST":
        try:
            provider = request.form.get("provider")
            existing = load_settings() or {}
            api_keys = dict(existing.get("api_keys") or {})
            submitted_key = (request.form.get("api_key") or "").strip()
            if submitted_key and provider:
                api_keys[provider] = submitted_key

            base_urls = dict(existing.get("base_urls") or {})
            submitted_url = (request.form.get("base_url") or "").strip().rstrip("/")
            if provider in URL_CONFIGURABLE_PROVIDERS:
                if submitted_url:
                    base_urls[provider] = submitted_url
                else:
                    base_urls.pop(provider, None)

            new_data = {
                **existing,
                "provider": provider,
                "model": request.form.get("model", settings_data.get("model")),
                "keep_alive": request.form.get("keep_alive", "5m"),
                "api_keys": api_keys,
                "base_urls": base_urls,
                "options": {
                    "num_predict":       int(request.form.get("num_predict", 256)),
                    "top_k":             int(request.form.get("top_k", 40)),
                    "top_p":             float(request.form.get("top_p", 0.9)),
                    "temperature":       float(request.form.get("temperature", 0.7)),
                    "num_ctx":           int(request.form.get("num_ctx", 2048)),
                    "num_batch":         int(request.form.get("num_batch", 4)),
                    "num_thread":        int(request.form.get("num_thread", 8)),
                    "num_gpu":           int(request.form.get("num_gpu", 0)),
                    "repeat_penalty":    float(request.form.get("repeat_penalty", 1.1)),
                    "use_mmap":          request.form.get("use_mmap") == "on",
                    "use_mlock":         request.form.get("use_mlock") == "on",
                    "penalize_newline":  request.form.get("penalize_newline") == "on",
                    "frequency_penalty": float(request.form.get("frequency_penalty", 0.0)),
                    "presence_penalty":  float(request.form.get("presence_penalty", 0.0)),
                }
            }

            save_settings(new_data)
            reset_engine()
            flash("Settings updated successfully!", "success")

        except Exception as e:
            logging.error(f"Error saving settings: {str(e)}")
            flash("Failed to save settings. Please check the logs for details.", "error")
            return redirect(url_for('settings.settings'))

    return render_template(
        'pages/settings.html',
        settings=settings_data,
        provider_fields=PROVIDER_FIELDS,
        provider_base_urls=PROVIDER_BASE_URLS,
        url_providers=URL_CONFIGURABLE_PROVIDERS,
        current_provider=provider,
        current_model=model,
        all_providers=list(PROVIDER_FIELDS.keys()),
        kernel_runtime=kernel_runtime(settings_data),
        security_runtime=security_runtime(settings_data),
        data_runtime=data_runtime(settings_data),
    )


# ----------------------------------------------------------------------------------------------------
# Kernel Lab

@settings_blueprint.route('/settings/kernel', methods=['POST'])
def save_kernel_settings():
    try:
        body = request.get_json(silent=True) or {}
        startup_code = body.get("startup_code", "")
        python_version = str(body.get("python_version", "3.12"))
        if python_version not in ALLOWED_PYTHON_VERSIONS:
            return jsonify({"error": f"Unsupported Python version: {python_version}"}), 400

        merge_settings_section("kernel", {
            "startup_code": startup_code,
            "python_version": python_version,
        })
        return jsonify({"status": "ok", "kernel": kernel_runtime()})
    except Exception as e:
        logging.error("save_kernel_settings failed: %s", e)
        return jsonify({"error": str(e)}), 500


def _image_installed_versions(image: str) -> dict[str, str]:
    """Best-effort map of {package_name_lower: version} installed in the kernel image.

    The kernel image defines an ENTRYPOINT (the ipykernel launcher), so we must
    override it with ``entrypoint`` — passing only a command would be appended as
    args to the launcher and never run pip.
    """
    try:
        client = get_docker_client()
        output = client.containers.run(
            image,
            entrypoint=["python", "-m", "pip", "list", "--format=json"],
            remove=True,
            stdout=True,
            stderr=False,
        )
        text = output.decode("utf-8") if isinstance(output, bytes) else output
        installed = json.loads(text)
        return {p.get("name", "").lower(): p.get("version", "") for p in installed}
    except Exception as e:
        logging.warning("Could not list image packages for %s: %s", image, e)
        return {}


@settings_blueprint.route('/settings/kernel/packages', methods=['GET'])
def list_kernel_packages():
    """Return every package installed in the kernel image (``pip list``), each
    flagged as user-managed or not. Managed packages that aren't installed yet
    (pending a rebuild/restart) are appended so the user always sees their list.

    The live image probe is best-effort: when Docker/the image is unavailable we
    fall back to just the managed list so the table still renders.
    """
    runtime = kernel_runtime()
    image = runtime["image"]
    managed = runtime.get("packages") or []
    managed_specs = {
        (p.get("name") or "").strip().lower(): (p.get("version") or "").strip()
        for p in managed if (p.get("name") or "").strip()
    }
    installed_versions = _image_installed_versions(image)

    packages = []
    seen: set[str] = set()
    for name_lower, version in sorted(installed_versions.items()):
        packages.append({
            "name": name_lower,
            "version": version,
            "managed": name_lower in managed_specs,
            "pinned": managed_specs.get(name_lower) or "",
            "installed": True,
        })
        seen.add(name_lower)

    # Managed packages not yet present in the image (pending install).
    for name_lower, version in managed_specs.items():
        if name_lower in seen:
            continue
        packages.append({
            "name": name_lower,
            "version": version,
            "managed": True,
            "pinned": version,
            "installed": False,
        })

    return jsonify({
        "packages": packages,
        "image": image,
        "image_available": bool(installed_versions),
        "managed_count": len(managed_specs),
    })


@settings_blueprint.route('/settings/kernel/packages/search')
def search_kernel_package():
    """Resolve a package name against PyPI (acts as 'pip search')."""
    import requests

    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "Query required"}), 400
    try:
        resp = requests.get(f"https://pypi.org/pypi/{query}/json", timeout=8)
        if resp.status_code == 404:
            return jsonify({"found": False, "query": query})
        resp.raise_for_status()
        info = (resp.json() or {}).get("info") or {}
        return jsonify({
            "found": True,
            "name": info.get("name", query),
            "version": info.get("version", ""),
            "summary": info.get("summary", "") or "",
            "home_page": info.get("home_page") or info.get("project_url") or "",
        })
    except Exception as e:
        logging.error("search_kernel_package failed: %s", e)
        return jsonify({"error": str(e)}), 500


@settings_blueprint.route('/settings/kernel/packages', methods=['POST'])
def add_kernel_package():
    try:
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        version = (body.get("version") or "").strip()
        if not name:
            return jsonify({"error": "Package name required"}), 400

        data = load_settings() or {}
        kernel = dict(data.get("kernel") or {})
        packages = list(kernel.get("packages") or [])
        entry = {"name": name, "version": version}
        packages = [p for p in packages if (p.get("name") or "").lower() != name.lower()]
        packages.append(entry)
        kernel["packages"] = packages
        data["kernel"] = kernel
        save_settings(data)
        return jsonify({"status": "ok", "packages": packages})
    except Exception as e:
        logging.error("add_kernel_package failed: %s", e)
        return jsonify({"error": str(e)}), 500


@settings_blueprint.route('/settings/kernel/packages/<string:package_name>', methods=['DELETE'])
def remove_kernel_package(package_name: str):
    try:
        data = load_settings() or {}
        kernel = dict(data.get("kernel") or {})
        packages = [
            p for p in (kernel.get("packages") or [])
            if (p.get("name") or "").lower() != package_name.lower()
        ]
        kernel["packages"] = packages
        data["kernel"] = kernel
        save_settings(data)
        return jsonify({"status": "ok", "packages": packages})
    except Exception as e:
        logging.error("remove_kernel_package failed: %s", e)
        return jsonify({"error": str(e)}), 500


@settings_blueprint.route('/settings/kernel/rebuild')
def rebuild_kernel_image():
    python_version = request.args.get("python_version") or kernel_runtime()["python_version"]
    if python_version not in ALLOWED_PYTHON_VERSIONS:
        return jsonify({"error": f"Unsupported Python version: {python_version}"}), 400

    def _package_specs() -> str:
        specs = []
        for pkg in kernel_runtime().get("packages") or []:
            name = (pkg.get("name") or "").strip()
            if not name:
                continue
            version = (pkg.get("version") or "").strip()
            specs.append(f"{name}=={version}" if version else name)
        return " ".join(specs)

    def generate():
        tag = f"spore-kernel:{python_version}"
        build_path = str(repo_root())
        extra_packages = _package_specs()
        try:
            client = get_docker_client()
            yield f"data: {json.dumps({'type': 'start', 'tag': tag})}\n\n"
            for line in client.api.build(
                path=build_path,
                dockerfile="docker/Dockerfile.kernel",
                tag=tag,
                buildargs={
                    "KERNEL_BASE_IMAGE": f"python:{python_version}-slim",
                    "EXTRA_PACKAGES": extra_packages,
                },
                decode=True,
            ):
                if "stream" in line:
                    chunk = {"type": "log", "content": line["stream"].rstrip()}
                    yield f"data: {json.dumps(chunk)}\n\n"
                elif "status" in line:
                    chunk = {"type": "status", "content": line["status"]}
                    if line.get("progress"):
                        chunk["progress"] = line["progress"]
                    yield f"data: {json.dumps(chunk)}\n\n"
                elif "error" in line:
                    chunk = {"type": "error", "content": line["error"]}
                    yield f"data: {json.dumps(chunk)}\n\n"
                    return
            yield f"data: {json.dumps({'type': 'done', 'tag': tag})}\n\n"
        except Exception as e:
            logging.error("rebuild_kernel_image failed: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


# ----------------------------------------------------------------------------------------------------
# Security & Compute Lab

@settings_blueprint.route('/settings/security', methods=['POST'])
def save_security_settings():
    try:
        body = request.get_json(silent=True) or {}
        mem_limit_mb = int(body.get("mem_limit_mb", 1024))
        pids_limit = int(body.get("pids_limit", 256))
        exec_timeout = int(body.get("exec_timeout", 30))
        mem_limit_mb = max(250, min(4096, mem_limit_mb))
        pids_limit = max(16, min(1024, pids_limit))
        exec_timeout = max(0, min(3600, exec_timeout))

        merge_settings_section("security", {
            "mem_limit_mb": mem_limit_mb,
            "pids_limit": pids_limit,
            "exec_timeout": exec_timeout,
        })
        return jsonify({"status": "ok", "security": security_runtime()})
    except Exception as e:
        logging.error("save_security_settings failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ----------------------------------------------------------------------------------------------------
# Data & Cache Lab

@settings_blueprint.route('/settings/data', methods=['POST'])
def save_data_settings():
    try:
        body = request.get_json(silent=True) or {}
        batch_row_size = int(body.get("batch_row_size") or 10_000)
        connect_timeout = int(body.get("connect_timeout") or 5)
        data_dir = (body.get("data_dir") or "").strip()
        session_permanent = bool(body.get("session_permanent", False))
        session_lifetime_hours = int(body.get("session_lifetime_hours") or 24)
        batch_row_size = max(100, min(1_000_000, batch_row_size))
        connect_timeout = max(1, min(120, connect_timeout))
        # 1 hour .. 1 year; ignored when session_permanent is set.
        session_lifetime_hours = max(1, min(8760, session_lifetime_hours))
        if not data_dir:
            return jsonify({"error": "data_dir required"}), 400

        merge_settings_section("data", {
            "batch_row_size": batch_row_size,
            "connect_timeout": connect_timeout,
            "data_dir": data_dir,
            "session_permanent": session_permanent,
            "session_lifetime_hours": session_lifetime_hours,
        })
        return jsonify({"status": "ok", "data": data_runtime()})
    except Exception as e:
        logging.error("save_data_settings failed: %s", e)
        return jsonify({"error": str(e)}), 500


@settings_blueprint.route('/settings/data/usage')
def data_usage():
    try:
        runtime = data_runtime()
        streams_dir = Path(runtime["data_dir"]) / "streams"
        total_bytes = 0
        stream_count = 0
        if streams_dir.is_dir():
            for root, _dirs, files in os.walk(streams_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        total_bytes += os.path.getsize(fpath)
                    except OSError:
                        pass
            stream_count = sum(
                1 for name in os.listdir(streams_dir)
                if (streams_dir / name).is_dir() and not name.startswith(".")
            )
        return jsonify({
            "data_dir": runtime["data_dir"],
            "streams_dir": str(streams_dir),
            "stream_count": stream_count,
            "total_bytes": total_bytes,
            "total_size": file_size_fmt(total_bytes),
        })
    except Exception as e:
        logging.error("data_usage failed: %s", e)
        return jsonify({"error": str(e)}), 500


@settings_blueprint.route('/settings/data/nuke-cache', methods=['POST'])
def nuke_cache():
    try:
        runtime = data_runtime()
        streams_dir = Path(runtime["data_dir"]) / "streams"
        active = _active_stream_names()
        removed: list[str] = []
        freed_bytes = 0

        if streams_dir.is_dir():
            for name in os.listdir(streams_dir):
                if name.startswith("."):
                    continue
                if name in active:
                    continue
                target = streams_dir / name
                if not target.is_dir():
                    continue
                for root, _dirs, files in os.walk(target):
                    for fname in files:
                        try:
                            freed_bytes += os.path.getsize(os.path.join(root, fname))
                        except OSError:
                            pass
                shutil.rmtree(target, ignore_errors=True)
                removed.append(name)

        return jsonify({
            "status": "ok",
            "removed": removed,
            "removed_count": len(removed),
            "freed_bytes": freed_bytes,
            "freed_size": file_size_fmt(freed_bytes),
        })
    except Exception as e:
        logging.error("nuke_cache failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ----------------------------------------------------------------------------------------------------
# Helper endpoints

@settings_blueprint.route('/models_list')
def models_list():
    provider = request.args.get("provider")
    if not provider:
        return jsonify({"error": "No provider specified"}), 400

    base_url = (request.args.get("base_url") or "").strip().rstrip("/") or None

    try:
        models = model_ls(provider, base_url)
        return jsonify(models)
    except Exception as e:
        logging.error(f"Failed to fetch models for {provider}: {e}")
        return jsonify({"error": "Could not connect to provider"}), 500
