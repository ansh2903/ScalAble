import os

def generate_blueprint(name):
    from flask import Blueprint
    template_folder, static_folder = get_frontend_paths()
    return Blueprint(
        name,
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
        static_url_path='/static'
)

def get_frontend_paths():
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
    FRONTEND_DIR = os.path.join(ROOT_DIR, 'frontend', 'src')
    return os.path.join(FRONTEND_DIR, 'templates'), os.path.join(FRONTEND_DIR, 'static')