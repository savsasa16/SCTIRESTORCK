from flask import Blueprint, render_template, redirect, session, url_for
from flask_login import login_required, current_user
from .utils import make_request
bp = Blueprint('selector', __name__)

@bp.route('/select_module')
@login_required
def select_module():
    if 'next_url' in session:
        next_url = session.pop('next_url', None)
        if next_url:
            return redirect(next_url)
            
    # ถ้าไม่มี, ให้แสดงหน้าเลือก Module ตามปกติ
    return render_template('select_module.html', current_user=current_user)