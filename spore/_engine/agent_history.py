"""Per-workspace agent conversation history."""

from __future__ import annotations

import threading

from langchain_community.chat_message_histories import ChatMessageHistory

_lock = threading.Lock()
_histories: dict[str, ChatMessageHistory] = {}
MAX_MESSAGES = 20


def get_agent_history(workspace_id: str) -> ChatMessageHistory:
    wid = workspace_id or "default"
    with _lock:
        if wid not in _histories:
            _histories[wid] = ChatMessageHistory()
        hist = _histories[wid]
        if len(hist.messages) > MAX_MESSAGES:
            hist.messages = hist.messages[-MAX_MESSAGES:]
        return hist


def clear_agent_history(workspace_id: str) -> None:
    wid = workspace_id or "default"
    with _lock:
        _histories.pop(wid, None)
