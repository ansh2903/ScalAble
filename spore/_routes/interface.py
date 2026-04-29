import os
from flask import session, render_template, flash
from spore._routes.utils import generate_blueprint
from spore._logger import logging

interface_blueprint = generate_blueprint('interface')

@interface_blueprint.route('/')
def index():
    try:
        connections = session.get('connections', {})
        return render_template('pages/index.html', connections=connections)
    except Exception as e:
        logging.error(f"Error loading index page: {str(e)}")
        flash("An error occurred while loading the index page.", "error")
        return render_template('pages/error.html', error_message="An error occurred.")