from flask import Flask
from src.interface.routes import interface_blueprint
from src.interface.auth import auth_blueprint
from src.config.settings import settings

from src.interface.user import db, bcrypt  # ✅ SQLAlchemy + bcrypt
import sys
from src.core.exception import CustomException
from src.core.logger import logging

def create_app():
    try:
        logging.info("Creating Flask app")
        app = Flask(__name__)
        app.secret_key = settings.SECRET_KEY

        # 🔧 Database config
        app.config["SQLALCHEMY_DATABASE_URI"] = settings.SQLALCHEMY_URI  # from settings.py
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        # 🔌 Initialize DB + bcrypt
        db.init_app(app)
        bcrypt.init_app(app)

        # 🧠 Initialize database (create tables)
        with app.app_context():
            db.create_all()

        # 🧩 Register Blueprints
        app.register_blueprint(interface_blueprint)
        app.register_blueprint(auth_blueprint)

        logging.info("Flask app created successfully")
        return app

    except Exception as e:
        logging.error(f"Error creating Flask app: {e}")
        raise CustomException(sys, e)


if __name__ == "__main__":
    print("Launching Flask server...")
    app = create_app()
    print(f"Server started on host: {settings.APP_HOST}")
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=settings.DEBUG)
