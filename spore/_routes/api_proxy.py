"""HTTP proxy for REST / GraphQL API connections from the workspace UI."""

from __future__ import annotations

import json
import time

from flask import jsonify, request, session

from spore._connectors.utils import requests_tls_kwargs
from spore._routes.utils import generate_blueprint
from spore._utils import decrypt_creds
from spore._logger import logging

api_proxy_blueprint = generate_blueprint("api_proxy")

MAX_BODY_BYTES = 5 * 1024 * 1024


def _find_connection(conn_id: str) -> dict | None:
    for conn in session.get("connections", []):
        if str(conn.get("id")) == str(conn_id):
            return conn
    return None


def _apply_auth(creds: dict, payload: dict) -> dict:
    """Build requests kwargs for auth from saved creds and optional UI override."""
    auth_type = payload.get("auth_type") or creds.get("auth_type") or "None"
    details_raw = payload.get("auth_details")
    if details_raw is None:
        details_raw = creds.get("auth_details") or "{}"
    if isinstance(details_raw, dict):
        details = details_raw
    else:
        try:
            details = json.loads(details_raw) if details_raw else {}
        except (json.JSONDecodeError, TypeError):
            details = {}

    kwargs: dict = {}
    headers = {}

    if auth_type == "API Key":
        key = details.get("api_key") or details.get("key")
        header_name = details.get("header", "X-API-Key")
        if key:
            if details.get("in") == "query":
                kwargs["params"] = kwargs.get("params") or {}
                param_name = details.get("param", "api_key")
                kwargs["params"][param_name] = key
            else:
                headers[header_name] = key
    elif auth_type == "Bearer Token":
        token = details.get("token") or details.get("bearer_token") or details.get("api_key")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "Basic Auth":
        user = details.get("username") or details.get("user")
        password = details.get("password") or ""
        if user:
            kwargs["auth"] = (user, password)

    if headers:
        kwargs["headers"] = headers
    return kwargs


@api_proxy_blueprint.route("/api/proxy/<string:conn_id>", methods=["POST"])
def api_proxy(conn_id: str):
    conn = _find_connection(conn_id)
    if not conn:
        return jsonify({"error": "Connection not found"}), 404

    source_type = (conn.get("source_type") or "").lower()
    if source_type not in ("rest_api", "graphql_api"):
        return jsonify({"error": "Not an API connection"}), 400

    payload = request.get_json(silent=True) or {}
    method = (payload.get("method") or "GET").upper()
    url = (payload.get("url") or "").strip()
    if not url:
        creds = decrypt_creds(conn.get("credentials") or {})
        url = (creds.get("endpoint") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    creds = decrypt_creds(conn.get("credentials") or {})
    tls = requests_tls_kwargs(creds)
    auth_kwargs = _apply_auth(creds, payload)

    req_headers = dict(auth_kwargs.pop("headers", {}))
    ui_headers = payload.get("headers") or {}
    if isinstance(ui_headers, list):
        for item in ui_headers:
            if isinstance(item, dict) and item.get("key"):
                req_headers[str(item["key"])] = str(item.get("value", ""))
    elif isinstance(ui_headers, dict):
        req_headers.update({str(k): str(v) for k, v in ui_headers.items()})

    params = dict(auth_kwargs.pop("params", {}) or {})
    ui_params = payload.get("params") or {}
    if isinstance(ui_params, list):
        for item in ui_params:
            if isinstance(item, dict) and item.get("key"):
                params[str(item["key"])] = str(item.get("value", ""))
    elif isinstance(ui_params, dict):
        params.update(ui_params)

    body = payload.get("body")
    json_body = None
    data_body = None
    if body is not None and body != "":
        if isinstance(body, dict):
            json_body = body
        else:
            stripped = str(body).strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    json_body = json.loads(stripped)
                except json.JSONDecodeError:
                    data_body = stripped
            else:
                data_body = stripped

    try:
        import requests

        t0 = time.monotonic()
        req_kwargs: dict = {
            "method": method,
            "url": url,
            "headers": req_headers,
            "params": params or None,
            "timeout": 60,
            "allow_redirects": True,
            **tls,
            **auth_kwargs,
        }
        if json_body is not None:
            req_kwargs["json"] = json_body
        elif data_body is not None:
            req_kwargs["data"] = data_body

        if source_type == "graphql_api" and json_body is None and method == "POST":
            req_kwargs["json"] = {"query": data_body or "query { __typename }"}

        response = requests.request(**req_kwargs)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        raw = response.content
        size_bytes = len(raw)
        truncated = False
        if size_bytes > MAX_BODY_BYTES:
            raw = raw[:MAX_BODY_BYTES]
            truncated = True

        try:
            body_text = raw.decode(response.encoding or "utf-8", errors="replace")
        except Exception:
            body_text = raw.decode("utf-8", errors="replace")

        if truncated:
            body_text += "\n\n… [response truncated]"

        resp_headers = {str(k): str(v) for k, v in response.headers.items()}

        return jsonify({
            "status": response.status_code,
            "time_ms": elapsed_ms,
            "size_bytes": size_bytes,
            "truncated": truncated,
            "headers": resp_headers,
            "body_text": body_text,
        })
    except Exception as e:
        logging.error(f"api proxy failed: {e}")
        return jsonify({"error": str(e)}), 502
