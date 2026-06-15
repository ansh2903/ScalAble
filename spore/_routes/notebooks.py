"""Notebook volume storage and HTML export."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from flask import jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from spore._logger import logging
from spore._routes.utils import generate_blueprint
from spore._utils import file_size_fmt, notebooks_dir
from spore._workspace.store import get_workspace_store

notebooks_blueprint = generate_blueprint("notebooks")


def _safe_notebook_name(name: str) -> str:
    raw = (name or "notebook").strip()
    base = secure_filename(raw) or "notebook"
    if not base.lower().endswith(".ipynb"):
        base = f"{base}.ipynb"
    return base


def _notebook_path(name: str) -> Path:
    root = notebooks_dir()
    path = (root / _safe_notebook_name(name)).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise ValueError("Invalid notebook path")
    return path


def _entry_meta(path: Path) -> dict:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    size = stat.st_size
    return {
        "name": path.name,
        "size_bytes": size,
        "size_pretty": file_size_fmt(size),
        "modified": modified,
    }


@notebooks_blueprint.route("/api/notebooks", methods=["GET"])
def api_list_notebooks():
    root = notebooks_dir()
    entries = []
    try:
        for name in sorted(os.listdir(root), key=str.lower):
            if name.startswith("."):
                continue
            path = root / name
            if path.is_file() and name.lower().endswith(".ipynb"):
                entries.append(_entry_meta(path))
    except OSError as e:
        logging.error("notebook list error: %s", e)
        return jsonify({"error": "Failed to list notebooks"}), 500
    entries.sort(key=lambda e: e.get("modified") or "", reverse=True)
    return jsonify({"notebooks": entries})


@notebooks_blueprint.route("/api/notebooks/save", methods=["POST"])
def api_save_notebook():
    data = request.get_json(silent=True) or {}
    name = data.get("name") or "notebook"
    ipynb = data.get("ipynb")
    if ipynb is None:
        return jsonify({"error": "ipynb payload required"}), 400

    try:
        if isinstance(ipynb, (dict, list)):
            content = json.dumps(ipynb, indent=1, ensure_ascii=False)
        else:
            content = str(ipynb)
        # Validate JSON
        json.loads(content)
        path = _notebook_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        meta = _entry_meta(path)
        return jsonify({"ok": True, **meta})
    except (json.JSONDecodeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    except OSError as e:
        logging.error("notebook save error: %s", e)
        return jsonify({"error": str(e)}), 500


@notebooks_blueprint.route("/api/notebooks/raw", methods=["GET"])
def api_notebook_raw():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        path = _notebook_path(name)
        if not path.is_file():
            return jsonify({"error": "Not found"}), 404
        return jsonify({"name": path.name, "content": path.read_text(encoding="utf-8")})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except OSError as e:
        logging.error("notebook raw error: %s", e)
        return jsonify({"error": str(e)}), 500


@notebooks_blueprint.route("/api/notebooks/upload", methods=["POST"])
def api_upload_notebook():
    uploaded = request.files.get("file") or request.files.get("files")
    if not uploaded:
        files = request.files.getlist("files")
        uploaded = files[0] if files else None
    if not uploaded:
        return jsonify({"error": "No file provided"}), 400

    raw_name = uploaded.filename or "notebook.ipynb"
    if not raw_name.lower().endswith(".ipynb"):
        return jsonify({"error": "Only .ipynb files are supported"}), 400

    try:
        path = _notebook_path(raw_name)
        if path.exists():
            overwrite = request.args.get("overwrite", "").lower() in ("1", "true", "yes")
            if not overwrite:
                return jsonify({"error": f"File already exists: {path.name}"}), 409
        path.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(path)
        meta = _entry_meta(path)
        return jsonify({"ok": True, **meta})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except OSError as e:
        logging.error("notebook upload error: %s", e)
        return jsonify({"error": str(e)}), 500


@notebooks_blueprint.route("/api/notebooks/download", methods=["GET"])
def api_download_notebook():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        path = _notebook_path(name)
        if not path.is_file():
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(path.parent, path.name, as_attachment=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@notebooks_blueprint.route("/api/notebooks", methods=["DELETE"])
def api_delete_notebook():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        path = _notebook_path(name)
        if not path.is_file():
            return jsonify({"error": "Not found"}), 404
        path.unlink()
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except OSError as e:
        logging.error("notebook delete error: %s", e)
        return jsonify({"error": str(e)}), 500


@notebooks_blueprint.route(
    "/api/workspaces/<string:workspace_id>/notebook/export-html",
    methods=["POST"],
)
def api_notebook_export_html(workspace_id):
    store = get_workspace_store()
    ws = store.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or ws.get("name") or "notebook").strip()
    cells = data.get("cells") or []

    html = render_template(
        "pages/notebook_export.html",
        workspace=ws,
        notebook_name=name,
        cells=cells,
    )
    buf = BytesIO(html.encode("utf-8"))
    filename = f"{name.replace(' ', '_')}.html"
    return send_file(
        buf,
        mimetype="text/html",
        as_attachment=True,
        download_name=filename,
    )
