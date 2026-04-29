from flask_socketio import emit
from flask import request
from spore._kernel.store import get_kernel, destroy_kernel
from spore._logger import logging

def register_kernel_events(socketio):

    @socketio.on('connect')
    def on_connect():
        session_id = request.sid
        logging.info(f"Client connected: {session_id}")
        emit('kernel_status', {'status': 'connected', 'session_id': session_id})
    
    @socketio.on('disconnect')
    def on_disconnect():
        session_id = request.sid
        destroy_kernel(session_id)
        logging.info(f"Client disconnected, kernel destroyed: {session_id}")

    @socketio.on('kernel_execute')
    def on_execute(data):
        session_id = request.sid
        code = data.get('code', '')
        cell_id = data.get('cell_id')
        kernel = get_kernel(session_id)

        socketio.start_background_task(
            _run_execution, socketio, session_id, cell_id, code  # pass socketio directly
        )

    @socketio.on('kernel_interrupt')
    def on_interrupt():
        session_id = request.sid
        get_kernel(session_id).interrupt()
        emit('kernel_status', {'status': 'interrupted'})

    @socketio.on('kernel_restart')
    def on_restart(data):
        session_id = request.sid
        kernel_name = data.get('kernel_name', 'python3')
        destroy_kernel(session_id)
        get_kernel(session_id, kernel_name)  # creates fresh one
        emit('kernel_status', {'status': 'restarted'})

    @socketio.on('kernel_list')
    def on_list():
        from spore._kernel.manager import SessionKernel
        emit('kernel_list', {'kernels': SessionKernel.available_kernels()})


def _run_execution(socketio, session_id, cell_id, code):
    kernel = get_kernel(session_id)
    for chunk in kernel.execute(code):
        chunk['cell_id'] = cell_id
        print(chunk)
        socketio.emit('kernel_output', chunk, to=session_id)