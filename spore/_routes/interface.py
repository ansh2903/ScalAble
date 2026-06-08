import os
from flask import session, render_template, flash
from spore._routes.utils import generate_blueprint
from spore._logger import logging
from spore._workspace.store import get_workspace_store
from spore._config.settings import VENDOR_CONFIG

interface_blueprint = generate_blueprint('interface')


def _source_icons() -> dict[str, str]:
    """Map each source_type id to its static icon path from VENDOR_CONFIG."""
    icons: dict[str, str] = {}
    for _category, items in VENDOR_CONFIG:
        for source_id, cfg in items.items():
            image = cfg.get("metadata", {}).get("image")
            if image:
                icons[source_id] = image
    return icons


@interface_blueprint.route('/')
def index():
    try:
        connections = session.get('connections', [])
        store = get_workspace_store()
        workspaces = store.list_workspaces()
        if not workspaces:
            store.create_workspace("Default Workspace", "Your first analysis workspace")
            workspaces = store.list_workspaces()
        return render_template(
            'pages/index.html',
            connections=connections,
            workspaces=workspaces,
            source_icons=_source_icons(),
        )
    except Exception as e:
        logging.error(f"Error loading index page: {str(e)}")
        flash("An error occurred while loading the index page.", "error")
        return render_template('pages/error.html', error_message="An error occurred.")