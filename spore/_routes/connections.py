import os
import tempfile

from flask import render_template, request, session, redirect, url_for, flash
from uuid_extensions import uuid7

from spore._routes.utils import generate_blueprint
from spore._connectors import SourceConnector
from spore._connectors.utils import (
    connection_stream_dir,
    is_data_field,
    is_secret_field,
    persist_data_file,
    persist_upload,
    purge_connection_data,
    purge_connection_secrets,
)
from spore._config.settings import VENDOR_CONFIG, COMMON_LAYERS

from spore._utils import encrypt_creds
from spore._logger import logging

connections_blueprint = generate_blueprint('connections')


def _parse_form_flags(data: dict) -> tuple[str, str, str, str, bool, bool, dict]:
    """Extract connection identity flags and return cleaned credential dict."""
    kind = data.pop("kind", "").lower()
    source_type = data.pop("source_type", "")
    name = data.pop("name", source_type)
    desc = data.pop("desc", "")
    use_ssh = data.pop("use_ssh", "false").lower() == "true"
    use_ssl = data.pop("use_ssl", "false").lower() == "true"
    cleaned = {k: v for k, v in data.items() if v not in ("", None)}
    return kind, source_type, name, desc, use_ssh, use_ssl, cleaned


def _save_temp_uploads(files, data: dict) -> list[str]:
    """Save uploaded files to temp paths for /test-connection; return paths to cleanup."""
    temp_paths: list[str] = []
    for file_key in files:
        f = files[file_key]
        if f and f.filename:
            ext = os.path.splitext(f.filename)[1] or ".pem"
            fd, tmp = tempfile.mkstemp(suffix=ext)
            with os.fdopen(fd, "wb") as out:
                f.save(out)
            data[file_key] = tmp
            temp_paths.append(tmp)
    return temp_paths


# Connections management (add, edit, delete)
@connections_blueprint.route('/connections', methods=['GET'])
def connections():
    """Source management and list page"""
    try:
        connections = session.get("connections", [])
        no_of_connections = len(connections) or 0

        return render_template(
            'pages/connections.html',
            connections=connections,
            no_of_connections=no_of_connections,
            config=VENDOR_CONFIG
        )

    except Exception as e:
        logging.error(f"connections list failed: {e}")
        return render_template('pages/error.html', error_message=str(e))


@connections_blueprint.route('/connections/new', methods=['GET', 'POST'])
def new_connector():
    return render_template("pages/connections_new.html", source=VENDOR_CONFIG)


@connections_blueprint.route('/connections/new/<vendor>', methods=['GET'])
def add_new_connection(vendor):
    try:
        source_config = None
        for category_name, items in VENDOR_CONFIG:
            if vendor in items:
                source_config = items[vendor]
                break

        if not source_config:
            return f"<div class='text-red-500'>Unsupported database type: {vendor}</div>", 404

        return render_template(
            'partials/form.html',
            kind=category_name,
            source_type=vendor,
            config=source_config,
            common_layers=COMMON_LAYERS
        )
    except Exception as e:
        logging.error(f"Template for {vendor} not found: {str(e)}")
        return render_template('pages/error.html', error_message=f"Template for {vendor} not found: {str(e)}")


@connections_blueprint.route('/test-connection', methods=['POST'])
def test_connection():
    data = request.form.to_dict()
    kind, source_type, _name, _desc, use_ssh, use_ssl, data = _parse_form_flags(data)

    temp_paths: list[str] = []
    try:
        if request.files:
            temp_paths = _save_temp_uploads(request.files, data)

        connector = SourceConnector(
            kind=kind,
            source_type=source_type,
            creds=encrypt_creds(data),
            use_ssh=use_ssh,
            use_ssl=use_ssl,
        )

        ok, msg = connector.test()
        return {"status": ok, "msg": msg}
    except Exception as e:
        return {"status": False, "msg": str(e)}

    finally:
        for path in temp_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as cleanup_err:
                logging.warning(f"Failed to cleanup temp file {path}: {cleanup_err}")


@connections_blueprint.route('/delete-connector/<conn_id>', methods=['GET'])
def delete_connector(conn_id):
    try:
        connections = session.get("connections", [])
        removed = next(
            (c for c in connections if str(c.get("id")) == str(conn_id)),
            None,
        )
        connections = [conn for conn in connections if str(conn.get("id")) != str(conn_id)]
        session["connections"] = connections
        session.modified = True

        purge_connection_secrets(conn_id)
        if removed:
            purge_connection_data(removed.get("_stream_dir"))
        flash("Database deleted successfully.", "success")
        return redirect(url_for('connections.connections'))
    except Exception as e:
        flash(f"Error deleting database: {str(e)}", "error")
        return redirect(url_for('connections.connections'))


@connections_blueprint.route('/registry', methods=['POST'])
def registry():
    data = request.form.to_dict()
    kind, source_type, name, desc, use_ssh, use_ssl, data = _parse_form_flags(data)

    conn_id = str(uuid7())
    stream_dir: str | None = None

    try:
        if request.files:
            for file_key in request.files:
                f = request.files[file_key]
                if not (f and f.filename):
                    continue
                if is_secret_field(file_key):
                    data[file_key] = persist_upload(conn_id, file_key, f)
                elif is_data_field(file_key):
                    if stream_dir is None:
                        stream_dir = connection_stream_dir(name, conn_id)
                    data[file_key] = persist_data_file(stream_dir, file_key, f)

        connector = SourceConnector(
            kind=kind,
            source_type=source_type,
            creds=encrypt_creds(data),
            use_ssh=use_ssh,
            use_ssl=use_ssl,
        )

        ok, msg = connector.test()
        if not ok:
            purge_connection_secrets(conn_id)
            purge_connection_data(stream_dir)
            flash(f"Connection failed: {msg}", "error")
            return redirect(url_for("connections.new_connector"))

        ok_meta, metadata = connector.fetch_metadata()
        if not ok_meta:
            metadata = {}

        conns = session.get("connections", [])
        entry = {
            "id": conn_id,
            "name": name,
            "kind": kind,
            "source_type": source_type,
            "desc": desc,
            "credentials": encrypt_creds(data),
            "metadata": metadata,
            "use_ssh": use_ssh,
            "use_ssl": use_ssl,
            "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if stream_dir:
            entry["_stream_dir"] = stream_dir
        conns.append(entry)
        session["connections"] = conns
        session.modified = True

        flash("Station linked.", "success")
        return redirect(url_for("connections.connections"))

    except Exception as e:
        logging.error(f"registry failed: {e}")
        purge_connection_secrets(conn_id)
        purge_connection_data(stream_dir)
        flash(f"System error: {e}", "error")
        return redirect(url_for("connections.new_connector"))
