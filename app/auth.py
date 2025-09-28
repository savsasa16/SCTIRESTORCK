from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from werkzeug.security import check_password_hash
from flask_login import login_user, logout_user, login_required, current_user

# Import from the parent directory
import database
from database import User # Assuming User class is in database.py

from .utils import make_request

# Create a Blueprint named 'auth'. This is how we group related routes.
bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Redirect to the module selector, not the index
        return redirect(url_for('selector.select_module'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = database.get_db_connection()
        user = User.get_by_username(conn, username)
        conn.close()

        if user and check_password_hash(user.password, password):
            login_user(user, remember=True)
            session.permanent = True
            flash('เข้าสู่ระบบสำเร็จ!', 'success')
            
            next_page = request.args.get('next')
            if next_page:
                session['next_url'] = next_page
            
            # IMPORTANT: Change the redirect to the selector blueprint
            return redirect(url_for('selector.select_module'))
        else:
            flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', 'danger')
            
    return render_template('login.html')

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('ออกจากระบบสำเร็จ!', 'success')
    # Redirect to the login page within this blueprint
    return redirect(url_for('auth.login'))