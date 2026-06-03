"""Dashboard widget query API."""

from __future__ import annotations

from flask import jsonify, request

from spore._compute.query import query_stream
from spore._routes.utils import generate_blueprint
from spore._logger import logging

dashboard_blueprint = generate_blueprint("dashboard")


@dashboard_blueprint.route("/api/widgets/query", methods=["POST"])
def api_widget_query():
    data = request.get_json(silent=True) or {}
    stream = (data.get("stream") or data.get("stream_name") or "").strip()
    if not stream:
        return jsonify({"error": "stream is required"}), 400

    transform = data.get("transform")
    sql = data.get("sql")
    limit = data.get("limit")

    try:
        result = query_stream(
            stream,
            transform=transform,
            sql=sql,
            limit=limit,
        )
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logging.error(f"widget query failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
