from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import bcrypt
from interface.user import User, db


auth_blueprint = Blueprint('auth', __name__)

# Dummy in-memory user store (use DB in production)
users = {
    "user@example.com":{
        "password": bcrypt.hashpw("password".encode(), bcrypt.gensalt()).decode()        
    }
}

@auth_blueprint.route('/guest', methods=['POST'])
def guest():
    session['user'] = 'guest'
    session['role'] = 'guest'
    session['connections'] = []  # start clean
    session['chat_history'] = []
    flash("You're now browsing as a guest!", "info")
    return redirect(url_for('interface.home'))


@auth_blueprint.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user'] = user.email
            session['role'] = user.role
            flash("Logged in successfully", "success")
            return redirect(url_for('interface.home'))

        flash("Invalid email or password", "danger")
    return render_template('login.html')



@auth_blueprint.route('/logout')
def logout():
    session.pop('user', None)
    flash("Logged out successfully", "info")
    return redirect(url_for('auth.login'))


@auth_blueprint.route('/login/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("User already exists.", "danger")
            return redirect(url_for('auth.register'))

        user = User(email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for('auth.login'))

    return render_template('register.html')
