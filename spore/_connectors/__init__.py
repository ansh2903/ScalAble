from spore._utils import decrypt_creds
from spore._logger import logging
from .registry import REGISTRY


class SourceConnector:
    def __init__(self, kind: str, source_type: str, creds: dict, use_ssh: bool, use_ssl: bool):
        self.kind        = kind
        self.source_type = source_type
        self.creds       = creds
        self.use_ssh     = use_ssh
        self.use_ssl     = use_ssl
        self._connector  = self._load_source()

    def _load_source(self):
        cls = REGISTRY.get(self.source_type)
        if not cls:
            raise ValueError(
                f"No source handler registered for '{self.source_type}'. "
                f"Available: {list(REGISTRY.keys())}"
            )
        config = decrypt_creds(self.creds) if self.creds else {}
        return cls(config, self.use_ssh, self.use_ssl)

    @property
    def capabilities(self):
        return self._connector.capabilities

    def test(self):
        ok, msg = self._connector.test_connection()
        logging.info(f"[{self.source_type}] test - {ok}: {msg}")
        return ok, msg

    def fetch_metadata(self):
        ok, meta = self._connector.fetch_metadata()
        logging.info(f"[{self.source_type}] metadata → {ok}")
        return ok, meta

    def preview(self, query: str, limit: int = 100):
        if not self._connector.capabilities.can_preview:
            yield {
                "type":    "error",
                "content": f"{self.source_type} doesn't support live preview. Ingest first."
            }
            return
        try:
            for chunk in self._connector.preview(query, limit):
                yield chunk
        except Exception as e:
            logging.error(f"[{self.source_type}] preview failed: {e}")
            yield {"type": "error", "content": str(e)}

    def ingest(self, stream_name: str, query: str, **kwargs):
        if not self._connector.capabilities.can_ingest:
            yield {"type": "error", "content": f"{self.source_type} does not support ingestion."}
            return
        try:
            result = self._connector.ingest(stream_name=stream_name, query=query, **kwargs)
            if hasattr(result, "__iter__") and not isinstance(result, tuple):
                yield from result
            else:
                status, payload = result
                if status == "success":
                    yield {"type": "done", "path": payload, "total_rows": None, "total_bytes": None}
                else:
                    yield {"type": "error", "content": payload}
        except Exception as e:
            logging.error(f"[{self.source_type}] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}

    def file_to_db(self, file_path: str, table_name: str, **kwargs):
        if not hasattr(self._connector, "file_to_db"):
            yield {
                "type": "error",
                "content": f"{self.source_type} does not support file push.",
            }
            return
        try:
            result = self._connector.file_to_db(
                file_path=file_path,
                table_name=table_name,
                **kwargs,
            )
            if hasattr(result, "__iter__") and not isinstance(result, (dict, tuple, str)):
                yield from result
            elif isinstance(result, dict) and result.get("ok") is False:
                yield {"type": "error", "content": result.get("error", "file_to_db failed")}
            elif isinstance(result, dict):
                yield {
                    "type": "done",
                    "table_name": table_name,
                    "total_rows": result.get("rows_inserted"),
                    "total_bytes": None,
                }
        except Exception as e:
            logging.error(f"[{self.source_type}] file_to_db failed: {e}")
            yield {"type": "error", "content": str(e)}