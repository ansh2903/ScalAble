from flask import Blueprint, session, render_template, flash
from src.core.logger import logging

interface_blueprint = Blueprint('interface', __name__)

@interface_blueprint.route('/')
def index():
    try:
        connections = session.get('connections', {})
        return render_template('index.html', connections=connections)
    except Exception as e:
        logging.error(f"Error loading index page: {str(e)}")
        flash("An error occurred while loading the index page.", "error")
        return render_template('error.html', error_message="An error occurred while loading the index page.")
