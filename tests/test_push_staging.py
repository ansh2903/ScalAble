"""Tests for push file staging, TTL sweep, and ephemeral cleanup."""

from __future__ import annotations

import io
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from spore._utils import streams_dir


@pytest.fixture
def push_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    streams = streams_dir(str(data_dir))
    streams.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SPORE_DATA_DIR", str(data_dir))
    from spore._config import settings as settings_mod

    settings_mod.settings.SPORE_DATA_DIR = str(data_dir)

    import spore._routes.fs as fs_mod
    import spore._routes.data as data_mod

    fs_mod.ROOT = str(streams)
    data_mod.STAGING_ROOT = os.path.join(fs_mod.ROOT, "_staging")
    data_mod.PUSH_STAGING_TTL_SECONDS = 1800

    import spore._utils as utils_mod

    monkeypatch.setattr(
        utils_mod,
        "data_runtime",
        lambda settings_data=None: {
            "batch_row_size": 10_000,
            "connect_timeout": 5,
            "data_dir": str(data_dir),
            "session_lifetime_seconds": 3600,
        },
    )

    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(data_mod.data_blueprint)

    return app.test_client(), data_mod, streams


def _stage_upload(client, filename: str, content: bytes) -> dict:
    data = {
        "file": (io.BytesIO(content), filename),
    }
    res = client.post(
        "/push/stage",
        data=data,
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    return res.get_json()


def _stage_volume(client, rel_path: str) -> dict:
    res = client.post(
        "/push/stage",
        json={"path": rel_path},
        content_type="application/json",
    )
    assert res.status_code == 200
    return res.get_json()


def test_upload_stage_sets_ephemeral_metadata(push_env):
    client, data_mod, _streams = push_env
    payload = _stage_upload(client, "sample.csv", b"a,b\n1,2\n")

    with client.session_transaction() as sess:
        entry = sess["push_staging"][payload["token"]]
        assert entry["ephemeral"] is True
        assert "staged_at" in entry
        assert os.path.isfile(entry["path"])


def test_volume_path_stage_sets_non_ephemeral(push_env):
    client, _data_mod, streams = push_env
    volume_file = streams / "imports.csv"
    volume_file.write_text("a,b\n1,2\n")

    payload = _stage_volume(client, "imports.csv")

    with client.session_transaction() as sess:
        entry = sess["push_staging"][payload["token"]]
        assert entry["ephemeral"] is False
        assert entry["path"] == str(volume_file)


def test_sweep_expired_staging_removes_ephemeral_files(push_env):
    client, data_mod, _streams = push_env
    payload = _stage_upload(client, "old.csv", b"x\n")

    with client.session_transaction() as sess:
        staging = dict(sess["push_staging"])
        staging[payload["token"]]["staged_at"] = (
            time.time() - data_mod.PUSH_STAGING_TTL_SECONDS - 1
        )
        path = staging[payload["token"]]["path"]
        sess["push_staging"] = staging

    client.post("/push/inspect", json={"token": "noop", "table_name": "t", "id": "1"})

    assert not os.path.isfile(path)
    token_dir = os.path.dirname(path)
    assert not os.path.isdir(token_dir)


def test_sweep_does_not_delete_volume_path_files(push_env):
    client, data_mod, streams = push_env
    volume_file = streams / "keepme.csv"
    volume_file.write_text("a\n1\n")
    payload = _stage_volume(client, "keepme.csv")

    with client.session_transaction() as sess:
        staging = dict(sess["push_staging"])
        staging[payload["token"]]["staged_at"] = (
            time.time() - data_mod.PUSH_STAGING_TTL_SECONDS - 1
        )
        sess["push_staging"] = staging

    client.post("/push/inspect", json={"token": "noop", "table_name": "t", "id": "1"})

    assert volume_file.is_file()


def test_release_staged_deletes_ephemeral_only(push_env):
    client, data_mod, streams = push_env
    os.makedirs(data_mod.STAGING_ROOT, exist_ok=True)
    token = "abc123"
    dest_dir = os.path.join(data_mod.STAGING_ROOT, token)
    os.makedirs(dest_dir)
    staged_path = os.path.join(dest_dir, "upload.csv")
    with open(staged_path, "w", encoding="utf-8") as fh:
        fh.write("a\n1\n")

    volume_file = streams / "persistent.csv"
    volume_file.write_text("a\n1\n")

    with client.application.test_request_context():
        from flask import session

        session["push_staging"] = {
            token: {
                "path": staged_path,
                "filename": "upload.csv",
                "ephemeral": True,
                "staged_at": time.time(),
            },
            "vol": {
                "path": str(volume_file),
                "filename": "persistent.csv",
                "ephemeral": False,
                "staged_at": time.time(),
            },
        }
        data_mod._release_staged(token, delete_file=True)
        data_mod._release_staged("vol", delete_file=True)

        assert token not in session["push_staging"]
        assert "vol" not in session["push_staging"]

    assert not os.path.isdir(dest_dir)
    assert volume_file.is_file()


def test_push_execute_success_deletes_ephemeral_staging(push_env):
    client, data_mod, _streams = push_env
    payload = _stage_upload(client, "pushme.csv", b"id\n1\n2\n")

    with client.session_transaction() as sess:
        entry = sess["push_staging"][payload["token"]]
        staged_path = entry["path"]

    conn_id = "pg-1"
    raw_conn = {
        "id": conn_id,
        "kind": "db",
        "source_type": "postgresql",
        "credentials": {},
    }

    def fake_file_to_db(file_path, table_name, batch_row_size):
        assert file_path == staged_path
        yield {"type": "start", "table_name": table_name, "est_total_rows": 2}
        yield {"type": "progress", "rows_so_far": 2, "bytes_so_far": 10, "batch_index": 1}
        yield {"type": "done", "table_name": table_name, "total_rows": 2, "total_bytes": 10}

    manager = MagicMock()
    manager.preview.return_value = iter([])
    manager.file_to_db.side_effect = fake_file_to_db
    manager.fetch_metadata.return_value = (True, {"schema": "public"})

    with patch.object(data_mod, "_connection_by_id", return_value=raw_conn), patch.object(
        data_mod, "_connector_for_conn", return_value=manager
    ):
        with client.session_transaction() as sess:
            sess["connections"] = [raw_conn]

        res = client.post(
            "/push/execute",
            json={
                "token": payload["token"],
                "table_name": "pushme",
                "id": conn_id,
                "ddl": "CREATE TABLE pushme (id INT);",
            },
        )
        assert res.status_code == 200
        body = res.get_data(as_text=True)
        assert '"type": "done"' in body or '"type":"done"' in body

    assert not os.path.isfile(staged_path)
    assert not os.path.isdir(os.path.dirname(staged_path))


def test_push_execute_failure_retains_ephemeral_staging(push_env):
    client, data_mod, _streams = push_env
    payload = _stage_upload(client, "retry.csv", b"id\n1\n")

    with client.session_transaction() as sess:
        staged_path = sess["push_staging"][payload["token"]]["path"]

    conn_id = "pg-1"
    raw_conn = {
        "id": conn_id,
        "kind": "db",
        "source_type": "postgresql",
        "credentials": {},
    }

    def failing_file_to_db(file_path, table_name, batch_row_size):
        yield {"type": "error", "content": "copy failed"}

    manager = MagicMock()
    manager.preview.return_value = iter([])
    manager.file_to_db.side_effect = failing_file_to_db

    with patch.object(data_mod, "_connection_by_id", return_value=raw_conn), patch.object(
        data_mod, "_connector_for_conn", return_value=manager
    ):
        with client.session_transaction() as sess:
            sess["connections"] = [raw_conn]

        res = client.post(
            "/push/execute",
            json={
                "token": payload["token"],
                "table_name": "retry_tbl",
                "id": conn_id,
                "ddl": "CREATE TABLE retry_tbl (id INT);",
            },
        )
        assert res.status_code == 200

    assert os.path.isfile(staged_path)
    with client.session_transaction() as sess:
        assert payload["token"] in sess["push_staging"]
