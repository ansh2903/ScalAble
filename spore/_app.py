from flask import Flask
from flask_session import Session
from flask_socketio import SocketIO

from spore._kernel.socket_events import register_kernel_events
from spore._config.settings import settings
from spore._config.settings import ALLOWED_ORIGINS

from spore._exception import CustomException
from spore._logger import logging

import redis
import sys
import os

socketio = SocketIO(cors_allowed_origins=ALLOWED_ORIGINS, async_mode='threading')

def create_app() -> Flask:
    """Creates Spore lol"""
    try:
        logging.info("Initializing Spore")
        static_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'src', 'templates', 'pages', 'static')
        
        app = Flask(__name__, 
                    static_folder=static_path, 
                    static_url_path='/static')
        app.secret_key = settings.SECRET_KEY
    
        configure_extensions(app)
        register_blueprints(app)
        register_sockets(app)

        return app

    except Exception as e:
        logging.error(f"Spore Initialisation failed: {e}")
        raise CustomException(e)

def configure_extensions(app: Flask) -> None:
    try:
        """Handle Redis, Sessions and other extensions."""
        app.config["SESSION_TYPE"] = "redis"
        app.config["SESSION_PERMANENT"] = True
        app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24
        app.config["SESSION_USE_SIGNER"] = True
        app.config["SESSION_KEY_PREFIX"] = "spore_session:"
        app.config["SESSION_REDIS"] = redis.StrictRedis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD
        )
        Session(app)
    except Exception as e:
        logging.info(f"failed to establish external connections.")
        raise CustomException(e)

def register_blueprints(app: Flask) -> None:
    """Register Spore Routes"""
    from spore._routes.interface import interface_blueprint
    from spore._routes.connections import connections_blueprint
    from spore._routes.workspace import workspace_blueprint
    from spore._routes.settings import settings_blueprint
    from spore._routes.data import data_blueprint
    from spore._routes.fs import fs_blueprint
    from spore._routes.api_proxy import api_proxy_blueprint
    from spore._routes.dashboard import dashboard_blueprint

    app.register_blueprint(interface_blueprint, name='interface')
    app.register_blueprint(connections_blueprint, name='connections')
    app.register_blueprint(workspace_blueprint, name='workspace')
    app.register_blueprint(settings_blueprint, name='settings')
    app.register_blueprint(data_blueprint, name='data')
    app.register_blueprint(fs_blueprint, name='fs')
    app.register_blueprint(api_proxy_blueprint, name='api_proxy')
    app.register_blueprint(dashboard_blueprint, name='dashboard')

def register_sockets(app: Flask) -> None:
    """Register Spore SocketIO (WebSockets) Events"""
    socketio.init_app(app)
    register_kernel_events(socketio)

# Entry point for Spore
if __name__ == "__main__":
    app = create_app()
    logging.info(f"Spore started on host: {settings.APP_HOST}")
    sys.stdout.flush()
    socketio.run(app, host=settings.APP_HOST, port=settings.APP_PORT, debug=settings.DEBUG)