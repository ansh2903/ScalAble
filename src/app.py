from flask import Flask
from src.interface.routes import interface_blueprint
from src.interface.auth import auth_blueprint
from src.config.settings import settings

import sys
from src.core.exception import CustomException
from src.core.logger import logging

def create_app():
    try:
        logging.info("Creating Flask app")
        app = Flask(__name__)
        app.secret_key = settings.SECRET_KEY

        # Register Blueprints
        app.register_blueprint(interface_blueprint)
        app.register_blueprint(auth_blueprint)

        logging.info("Flask app created successfully")
        return app

    except Exception as e:
        logging.error(f"Error creating Flask app: {e}")
        raise CustomException(str(e), sys)


if __name__ == "__main__":
    print("Launching Flask server...")
    app = create_app()
    print(f"Server started on host: {settings.APP_HOST}")
    app.run(host='127.0.0.1', port=5000, debug=settings.DEBUG)