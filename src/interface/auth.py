from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import hashlib
auth_blueprint = Blueprint('auth', __name__)

# Dummy in-memory user store (use DB in production)
users = {"test@example.com": {"password": hashlib.sha256("1234".encode()).hexdigest(), "databases": []}}

@auth_blueprint.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()

        user = users.get(email)
        if user and user['password'] == password:
            session['user'] = email
            flash("Logged in successfully", "success")
            return redirect(url_for('interface.home'))
        flash("Invalid credentials", "danger")

    return render_template('login.html')

@auth_blueprint.route('/logout')
def logout():
    session.pop('user', None)
    flash("Logged out successfully", "info")
    return redirect(url_for('auth.login'))

@auth_blueprint.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        users[email] = {"password": password, "databases": []}
        flash("Registration successful. Please login.", "success")
        return redirect(url_for('auth.login'))
    return render_template('register.html')
