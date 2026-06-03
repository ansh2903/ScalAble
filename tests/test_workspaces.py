"""Tests for SQLite workspace store and HTTP API."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from spore._workspace.store import WorkspaceStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_workspaces.db"
    s = WorkspaceStore(db)
    s.initialize()
    return s


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Minimal Flask app with workspace routes only (no LLM/connector imports)."""
    monkeypatch.setenv("SPORE_DATA_DIR", str(tmp_path))
    import spore._workspace.store as ws_mod
    from spore._config.settings import settings

    monkeypatch.setattr(settings, "SPORE_DATA_DIR", str(tmp_path))
    ws_mod._store = WorkspaceStore(tmp_path / "workspaces.db")
    ws_mod._store.initialize()

    from flask import Flask, jsonify, request
    from spore._workspace.store import get_workspace_store

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.get("/api/workspaces")
    def list_ws():
        return jsonify({"workspaces": get_workspace_store().list_workspaces()})

    @app.post("/api/workspaces")
    def create_ws():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        ws = get_workspace_store().create_workspace(name, (data.get("description") or "").strip())
        return jsonify({"workspace": ws}), 201

    @app.patch("/api/workspaces/<workspace_id>")
    def patch_ws(workspace_id):
        data = request.get_json(silent=True) or {}
        ws = get_workspace_store().update_workspace(
            workspace_id, name=data.get("name"), description=data.get("description")
        )
        if not ws:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"workspace": ws})

    @app.get("/api/workspaces/<workspace_id>/state")
    def get_state(workspace_id):
        store = get_workspace_store()
        if not store.get_workspace(workspace_id):
            return jsonify({"error": "Not found"}), 404
        return jsonify({"state": store.get_state(workspace_id)})

    @app.patch("/api/workspaces/<workspace_id>/state")
    def patch_state(workspace_id):
        store = get_workspace_store()
        if not store.get_workspace(workspace_id):
            return jsonify({"error": "Not found"}), 404
        state = store.patch_state(workspace_id, request.get_json(silent=True) or {})
        return jsonify({"state": state})

    @app.post("/api/workspaces/<workspace_id>/history")
    def post_history(workspace_id):
        store = get_workspace_store()
        if not store.get_workspace(workspace_id):
            return jsonify({"error": "Not found"}), 404
        data = request.get_json(silent=True) or {}
        entry = store.append_history(workspace_id, data)
        return jsonify({"entry": entry}), 201

    @app.get("/api/workspaces/<workspace_id>/history")
    def get_history(workspace_id):
        store = get_workspace_store()
        if not store.get_workspace(workspace_id):
            return jsonify({"error": "Not found"}), 404
        return jsonify({"history": store.list_history(workspace_id)})

    @app.delete("/api/workspaces/<workspace_id>")
    def delete_ws(workspace_id):
        store = get_workspace_store()
        if not store.delete_workspace(workspace_id):
            return jsonify({"error": "Not found"}), 404
        if not store.list_workspaces():
            store.create_workspace("Default Workspace", "Your first analysis workspace")
        return jsonify({"ok": True})

    return app.test_client()


def test_store_wal_mode(store):
    assert store.journal_mode().lower() == "wal"


def test_create_list_update_delete(store):
    ws = store.create_workspace("Alpha", "First workspace")
    assert ws["name"] == "Alpha"
    assert ws["description"] == "First workspace"

    listed = store.list_workspaces()
    assert len(listed) == 1
    assert listed[0]["id"] == ws["id"]

    updated = store.update_workspace(ws["id"], name="Alpha Renamed")
    assert updated["name"] == "Alpha Renamed"

    assert store.delete_workspace(ws["id"]) is True
    assert store.get_workspace(ws["id"]) is None


def test_state_patch(store):
    ws = store.create_workspace("State Test")
    state = store.get_state(ws["id"])
    assert state["active_view"] == "data"
    assert state["notebook"]["cells"] == []

    patched = store.patch_state(
        ws["id"],
        {
            "active_view": "analyze",
            "selected_connection_id": "conn-1",
            "notebook": {"cells": [{"id": "cell-1", "type": "python", "code": "1+1"}]},
            "dashboard": {"widgets": [{"id": "w1"}], "title": "My Dash"},
        },
    )
    assert patched["active_view"] == "analyze"
    assert patched["selected_connection_id"] == "conn-1"
    assert len(patched["notebook"]["cells"]) == 1
    assert patched["dashboard"]["widgets"][0]["id"] == "w1"


def test_history_scoped_by_workspace(store):
    a = store.create_workspace("A")
    b = store.create_workspace("B")

    store.append_history(a["id"], {"query": "SELECT 1", "status": "success"})
    store.append_history(b["id"], {"query": "SELECT 2", "status": "success"})

    hist_a = store.list_history(a["id"])
    hist_b = store.list_history(b["id"])
    assert len(hist_a) == 1
    assert len(hist_b) == 1
    assert hist_a[0]["query"] == "SELECT 1"
    assert hist_b[0]["query"] == "SELECT 2"

    store.clear_history(a["id"])
    assert len(store.list_history(a["id"])) == 0
    assert len(store.list_history(b["id"])) == 1


def test_api_workspaces_crud(app_client):
    res = app_client.post(
        "/api/workspaces",
        data=json.dumps({"name": "API WS", "description": "via test"}),
        content_type="application/json",
    )
    assert res.status_code == 201
    wid = res.get_json()["workspace"]["id"]

    res = app_client.get("/api/workspaces")
    assert res.status_code == 200
    ids = [w["id"] for w in res.get_json()["workspaces"]]
    assert wid in ids

    res = app_client.patch(
        f"/api/workspaces/{wid}",
        data=json.dumps({"name": "Renamed"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.get_json()["workspace"]["name"] == "Renamed"

    res = app_client.get(f"/api/workspaces/{wid}/state")
    assert res.status_code == 200
    assert res.get_json()["state"]["active_view"] == "data"

    res = app_client.patch(
        f"/api/workspaces/{wid}/state",
        data=json.dumps({"active_view": "dashboard"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.get_json()["state"]["active_view"] == "dashboard"

    res = app_client.post(
        f"/api/workspaces/{wid}/history",
        data=json.dumps({"query": "SELECT 42", "status": "success", "timestamp": 1000}),
        content_type="application/json",
    )
    assert res.status_code == 201

    res = app_client.get(f"/api/workspaces/{wid}/history")
    assert res.status_code == 200
    assert len(res.get_json()["history"]) == 1

    res = app_client.delete(f"/api/workspaces/{wid}")
    assert res.status_code == 200


def test_ensure_default_workspace(store):
    first = store.ensure_default_workspace()
    second = store.ensure_default_workspace()
    assert first["id"] == second["id"]
    assert len(store.list_workspaces()) == 1
