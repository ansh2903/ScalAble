from flask import Flask
from flask_session import Session
from flask_socketio import SocketIO
import redis
import sys

from src.kernel.socket_events import register_kernel_events
from src.routes.interface import interface_blueprint
from src.routes.endpoints import endpoints_blueprint
from src.config.settings import settings
from src.core.exception import CustomException
from src.core.logger import logging

# TODO: RESTRICT CORS IN THE FUTURE, IT CAN LEAD TO REMOTE CODE EXECUTION WHICH IS A NO NO.
# FAILURE TO DO SO WILL LEED TO PUBLIC HANGING AND BEATING FOR YOU. 
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')

def create_app():
    try:
        logging.info("Creating Flask app")
        app = Flask(__name__)
        app.secret_key = settings.SECRET_KEY

        app.config["SESSION_TYPE"] = "redis"
        app.config["SESSION_PERMANENT"] = True
        app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24
        app.config["SESSION_USE_SIGNER"] = True
        app.config["SESSION_KEY_PREFIX"] = "scalable_session:"
        app.config["SESSION_REDIS"] = redis.StrictRedis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD
        )
        Session(app)

        app.register_blueprint(interface_blueprint, name='interface')
        app.register_blueprint(endpoints_blueprint, name='endpoints')

        socketio.init_app(app)

        register_kernel_events(socketio)

        logging.info("Flask app created successfully")
        return app

    except Exception as e:
        logging.error(f"Error creating Flask app: {e}")
        raise CustomException(str(e), sys)

if __name__ == "__main__":
    print("Launching Flask server...")
    app = create_app()
    print(f"Server started on host: {settings.APP_HOST}")
    sys.stdout.flush()
    socketio.run(app, host=settings.APP_HOST, port=settings.APP_PORT, debug=settings.DEBUG)