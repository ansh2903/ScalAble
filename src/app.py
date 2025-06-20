from flask import Flask
from src.interface.routes import interface_blueprint
from src.core.logger import logging

logging.INFO("Starting the Flask application...")
def create_app():
    app = Flask(__name__)
    app.secret_key = "scalable_secret_key"
    app.register_blueprint(interface_blueprint)
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)