from flask_socketio import emit
from flask import request, session, copy_current_request_context
from spore._kernel.store import get_kernel, destroy_kernel
from spore._logger import logging
from spore._engine.agent import WorkspaceAgent
from spore._engine.agent_history import clear_agent_history
from spore._engine.agent_pending import (
    clear_interrupt,
    deliver_result,
    register_interrupt,
    trigger_interrupt,
)

def register_kernel_events(socketio):

    @socketio.on('connect')
    def on_connect():
        session_id = request.sid
        logging.info(f"Client connected: {session_id}")
        emit('kernel_status', {'status': 'connected', 'session_id': session_id})
    
    @socketio.on('disconnect')
    def on_disconnect():
        session_id = request.sid
        trigger_interrupt(session_id)
        clear_interrupt(session_id)
        destroy_kernel(session_id)
        logging.info(f"Client disconnected, kernel destroyed: {session_id}")

    @socketio.on('kernel_execute')
    def on_execute(data):
        session_id = request.sid
        code = data.get('code', '')
        cell_id = data.get('cell_id')
        kernel = get_kernel(session_id)

        socketio.start_background_task(
            _run_execution, socketio, session_id, cell_id, code
        )

    @socketio.on('kernel_interrupt')
    def on_interrupt():
        session_id = request.sid
        get_kernel(session_id).interrupt()
        emit('kernel_status', {'status': 'interrupted'})

    @socketio.on('kernel_restart')
    def on_restart(data):
        session_id = request.sid
        destroy_kernel(session_id)
        get_kernel(session_id)
        emit('kernel_status', {'status': 'restarted'})

    @socketio.on('kernel_list')
    def on_list():
        from spore._kernel.manager import DockerKernel
        emit('kernel_list', {'kernels': DockerKernel.available_kernels()})

    @socketio.on('agent_run')
    def on_agent_run(data):
        session_id = request.sid
        message = (data or {}).get('message', '')
        workspace_id = (data or {}).get('workspace_id') or session.get('active_workspace_id')
        context = (data or {}).get('context') or {}
        clear_interrupt(session_id)
        register_interrupt(session_id)

        @copy_current_request_context
        def run():
            _run_agent(socketio, session_id, workspace_id, message, context)

        socketio.start_background_task(run)

    @socketio.on('agent_tool_result')
    def on_agent_tool_result(data):
        session_id = request.sid
        payload = data or {}
        request_id = payload.get('request_id')
        if not request_id:
            return
        deliver_result(session_id, request_id, payload)

    @socketio.on('agent_interrupt')
    def on_agent_interrupt():
        session_id = request.sid
        trigger_interrupt(session_id)
        emit('agent_event', {'type': 'interrupted', 'content': 'Agent stopped'})

    @socketio.on('agent_reset')
    def on_agent_reset(data):
        workspace_id = (data or {}).get('workspace_id') or session.get('active_workspace_id') or 'default'
        clear_agent_history(workspace_id)
        emit('agent_event', {'type': 'reset_done'})


def _json_safe(value):
    """Recursively coerce agent event payloads into JSON-serializable values.

    Query results can contain datetime/date, Decimal, numpy scalars, bytes, etc.
    Socket.IO uses the stdlib json encoder, so these must be converted before emit.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            return str(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass
    return str(value)


def _run_agent(socketio, session_id, workspace_id, message, context):
    try:
        agent = WorkspaceAgent(workspace_id=workspace_id or 'default', session_id=session_id)
        for event in agent.run(message, context):
            socketio.emit('agent_event', _json_safe(event), to=session_id)
    except Exception as exc:
        logging.error("Agent run failed: %s", exc, exc_info=True)
        socketio.emit(
            'agent_event',
            {'type': 'error', 'content': str(exc)},
            to=session_id,
        )
    finally:
        clear_interrupt(session_id)


def _run_execution(socketio, session_id, cell_id, code):
    kernel = get_kernel(session_id)
    for chunk in kernel.execute(code):
        chunk['cell_id'] = cell_id
        print(chunk)
        socketio.emit('kernel_output', chunk, to=session_id)