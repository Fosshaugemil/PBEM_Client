from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import select

from .. import db
from ..models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Username and password are required.')
            return render_template('auth/register.html')

        if db.session.execute(select(User).filter_by(username=username)).scalar_one_or_none():
            flash('Username already taken.')
            return render_template('auth/register.html')

        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Account created. Please log in.')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = db.session.execute(select(User).filter_by(username=username)).scalar_one_or_none()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid username or password.')
            return render_template('auth/login.html')

        session.clear()
        session['user_id'] = user.id
        session['username'] = user.username
        return redirect(url_for('lobby.list_lobbies'))

    return render_template('auth/login.html')


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
