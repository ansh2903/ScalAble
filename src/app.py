from flask import Flask
from src.interface.routes import interface_blueprint
from src.interface.auth import auth_blueprint
from src.config.settings import settings

from src.core.logger import logging

logging.info("Starting the Flask application...")

def create_app():
    app = Flask(__name__)
    app.secret_key = settings.SECRET_KEY
    app.register_blueprint(interface_blueprint)
    app.register_blueprint(auth_blueprint)
    return app

if __name__ == "__main__":
    print("Launching Flask server...")
    app = create_app()
    app.run(debug=True) # http://127.0.0.1:5000/