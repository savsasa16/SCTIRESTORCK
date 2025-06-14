# app.py
import sqlite3
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import re
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_file, current_app
import pandas as pd
from io import BytesIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os

import database # Your existing database.py file

# *** เพิ่ม Cloudinary imports ***
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_super_secret_key_here_please_change_this_to_a_complex_random_string')

app.config['UPLOAD_FOLDER'] = 'uploads'

# *** ตั้งค่า Cloudinary (ใช้ Environment Variables) ***
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

ALLOWED_EXCEL_EXTENSIONS = {'xlsx', 'xls'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Define Bangkok timezone
BKK_TZ = pytz.timezone('Asia/Bangkok')

# --- Helper Functions ---
def allowed_excel_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXCEL_EXTENSIONS

def allowed_image_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def get_db():
    if 'db' not in g:
        g.db = database.get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def get_bkk_time():
    return datetime.now(BKK_TZ)

# Helper to convert a timestamp to BKK timezone
def convert_to_bkk_time(timestamp_obj):
    if timestamp_obj is None:
        return None
    
    # If the timestamp is a string, parse it first
    if isinstance(timestamp_obj, str):
        try:
            # datetime.fromisoformat can handle timezone info if present
            dt_obj = datetime.fromisoformat(timestamp_obj)
        except ValueError:
            # Fallback for non-isoformat strings, if necessary, or return None
            # For this context, assuming isoformat or datetime object
            return None
    elif isinstance(timestamp_obj, datetime):
        dt_obj = timestamp_obj
    else:
        return None # Not a datetime object or string

    # If datetime object is naive (no timezone info), assume it's UTC and localize
    if dt_obj.tzinfo is None:
        dt_obj = pytz.utc.localize(dt_obj)
    
    # Convert to BKK timezone
    return dt_obj.astimezone(BKK_TZ)

@app.context_processor
def inject_global_data():
    return dict(get_bkk_time=get_bkk_time)

# --- Flask-Login Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    return database.User.get(conn, user_id)

# --- Login/Logout Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = database.User.get_by_username(conn, username)

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('เข้าสู่ระบบสำเร็จ!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('ออกจากระบบสำเร็จ!', 'success')
    return redirect(url_for('login'))

# --- Helper function for processing report tables in app.py (for index and daily_stock_report) ---
def process_tire_report_data(all_tires):
    processed_report = []
    brand_summaries = defaultdict(lambda: {'quantity_sum': 0})
    
    sorted_tires = sorted(all_tires, key=lambda x: (x['brand'], x['model'], x['size']))
    
    last_brand = None
    for tire in sorted_tires:
        current_brand = tire['brand']
        
        if last_brand is not None and current_brand != last_brand:
            summary_data = brand_summaries[last_brand]
            processed_report.append({
                'is_summary': True,
                'brand': last_brand,
                'quantity': summary_data['quantity_sum']
            })
        
        processed_report.append({
            'is_summary': False,
            'brand': tire['brand'],
            'model': tire['model'],
            'size': tire['size'],
            'quantity': tire['quantity'],
            'price_per_item': tire['price_per_item'],
            'promotion_id': tire['promotion_id'],
            'promo_is_active': tire['promo_is_active'],
            'promo_name': tire['promo_name'],
            'display_promo_description_text': tire['display_promo_description_text'],
            'display_promo_price_per_item': tire['display_promo_price_per_item'],
            'display_price_for_4': tire['display_price_for_4'],
            'year_of_manufacture': tire['year_of_manufacture'],
            'id': tire['id']
        })
        
        brand_summaries[current_brand]['quantity_sum'] += tire['quantity']
        
        last_brand = current_brand
        
    if last_brand is not None:
        summary_data = brand_summaries[last_brand]
        processed_report.append({
            'is_summary': True,
            'brand': last_brand,
            'quantity': summary_data['quantity_sum']
        })
        
    return processed_report

def process_wheel_report_data(all_wheels):
    processed_report = []
    brand_summaries = defaultdict(lambda: {'quantity_sum': 0})

    sorted_wheels = sorted(all_wheels, key=lambda x: (x['brand'], x['model'], x['diameter'], x['width'], x['pcd']))

    last_brand = None
    for wheel in sorted_wheels:
        current_brand = wheel['brand']

        if last_brand is not None and current_brand != last_brand:
            summary_data = brand_summaries[last_brand]
            processed_report.append({
                'is_summary': True,
                'brand': last_brand,
                'quantity': summary_data['quantity_sum']
            })

        processed_report.append({
            'is_summary': False,
            'brand': wheel['brand'],
            'model': wheel['model'],
            'diameter': wheel['diameter'],
            'pcd': wheel['pcd'],
            'width': wheel['width'],
            'et': wheel['et'],
            'color': wheel['color'],
            'quantity': wheel['quantity'],
            'cost': wheel['cost'],
            'retail_price': wheel['retail_price'],
            'image_filename': wheel['image_filename'],
            'id': wheel['id']
        })

        brand_summaries[current_brand]['quantity_sum'] += wheel['quantity']

        last_brand = current_brand

    if last_brand is not None:
        summary_data = brand_summaries[last_brand]
        processed_report.append({
            'is_summary': True,
            'brand': last_brand,
            'quantity': summary_data['quantity_sum']
        })
    
    return processed_report


@app.route('/')
@login_required
def index():
    conn = get_db()

    tire_query = request.args.get('tire_query', '').strip()
    tire_selected_brand = request.args.get('tire_brand_filter', 'all').strip()

    all_tires = database.get_all_tires(conn, query=tire_query, brand_filter=tire_selected_brand, include_deleted=False)
    
    available_tire_brands = database.get_all_tire_brands(conn)

    processed_tires_for_display = process_tire_report_data(all_tires)
    
    wheel_query = request.args.get('wheel_query', '').strip()
    wheel_selected_brand = request.args.get('wheel_brand_filter', 'all').strip()

    all_wheels = database.get_all_wheels(conn, query=wheel_query, brand_filter=wheel_selected_brand, include_deleted=False)

    available_wheel_brands = database.get_all_wheel_brands(conn) 

    processed_wheels_for_display = process_wheel_report_data(all_wheels)
    
    active_tab = request.args.get('tab', 'tires')

    return render_template('index.html',
                           tires_for_display=processed_tires_for_display,
                           wheels_for_display=processed_wheels_for_display,
                           
                           tire_query=tire_query,
                           available_tire_brands=available_tire_brands,
                           tire_selected_brand=tire_selected_brand,
                           wheel_query=wheel_query,
                           available_wheel_brands=available_wheel_brands,
                           wheel_selected_brand=wheel_selected_brand,

                           active_tab=active_tab)

# --- Promotions Routes ---
@app.route('/promotions')
@login_required
def promotions():
    conn = get_db()
    all_promotions = database.get_all_promotions(conn, include_inactive=True)
    return render_template('promotions.html', promotions=all_promotions)

@app.route('/add_promotion', methods=('GET', 'POST'))
@login_required
def add_promotion():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการเพิ่มโปรโมชัน', 'danger')
        return redirect(url_for('promotions'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        promo_type = request.form['type'].strip()
        value1 = request.form['value1'].strip()
        value2 = request.form.get('value2', '').strip()
        is_active = request.form.get('is_active') == '1'

        if not name or not promo_type or not value1:
            flash('กรุณากรอกข้อมูลโปรโมชันให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
        else:
            try:
                value1 = float(value1)
                value2 = float(value2) if value2 else None

                if promo_type == 'buy_x_get_y' and (value2 is None or value1 <= 0 or value2 <= 0):
                    raise ValueError("สำหรับ 'ซื้อ X แถม Y' โปรดระบุ X และ Y ที่มากกว่า 0")
                elif promo_type == 'percentage_discount' and (value1 <= 0 or value1 > 100):
                    raise ValueError("ส่วนลดเปอร์เซ็นต์ต้องอยู่ระหว่าง 0-100")
                elif promo_type == 'fixed_price_per_n' and value1 <= 0:
                    raise ValueError("ราคาพิเศษต้องมากกว่า 0")

                conn = get_db()
                database.add_promotion(conn, name, promo_type, value1, value2, is_active)
                flash('เพิ่มโปรโมชันใหม่สำเร็จ!', 'success')
                return redirect(url_for('promotions'))
            except ValueError as e:
                flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ชื่อโปรโมชัน "{name}" มีอยู่ในระบบแล้ว', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มโปรโมชัน: {e}', 'danger')

    return render_template('add_promotion.html')

@app.route('/edit_promotion/<int:promo_id>', methods=('GET', 'POST'))
@login_required
def edit_promotion(promo_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขโปรโมชัน', 'danger')
        return redirect(url_for('promotions'))
    conn = get_db()
    promotion = database.get_promotion(conn, promo_id)

    if promotion is None:
        flash('ไม่พบโปรโมชันที่ระบุ', 'danger')
        return redirect(url_for('promotions'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        promo_type = request.form['type'].strip()
        value1 = request.form['value1'].strip()
        value2 = request.form.get('value2', '').strip()
        is_active = request.form.get('is_active') == '1'

        if not name or not promo_type or not value1:
            flash('กรุณากรอกข้อมูลโปรโมชันให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
        else:
            try:
                value1 = float(value1)
                value2 = float(value2) if value2 else None

                if promo_type == 'buy_x_get_y' and (value2 is None or value1 <= 0 or value2 <= 0):
                    raise ValueError("สำหรับ 'ซื้อ X แถม Y' โปรดระบุ X และ Y ที่มากกว่า 0")
                elif promo_type == 'percentage_discount' and (value1 <= 0 or value1 > 100):
                    raise ValueError("ส่วนลดเปอร์เซ็นต์ต้องอยู่ระหว่าง 0-100")
                elif promo_type == 'fixed_price_per_n' and value1 <= 0:
                    raise ValueError("ราคาพิเศษต้องมากกว่า 0")

                conn = get_db()
                database.update_promotion(conn, promo_id, name, promo_type, value1, value2, is_active)
                flash('แก้ไขโปรโมชันสำเร็จ!', 'success')
                return redirect(url_for('promotions'))
            except ValueError as e:
                flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ชื่อโปรโมชัน "{name}" มีอยู่ในระบบแล้ว', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขโปรโมชัน: {e}', 'danger')

    return render_template('edit_promotion.html', promotion=promotion)

@app.route('/delete_promotion/<int:promo_id>', methods=('POST',))
@login_required
def delete_promotion(promo_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการลบโปรโมชัน', 'danger')
        return redirect(url_for('promotions'))
    conn = get_db()
    promotion = database.get_promotion(conn, promo_id)

    if promotion is None:
        flash('ไม่พบโปรโมชันที่ระบุ', 'danger')
    else:
        try:
            database.delete_promotion(conn, promo_id)
            flash('ลบโปรโมชันสำเร็จ! สินค้าที่เคยใช้โปรโมชันนี้จะถูกตั้งค่าโปรโมชันเป็น "ไม่มี"', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบโปรโมชัน: {e}', 'danger')

    return redirect(url_for('promotions'))


# --- Tire Routes (Main item editing) ---
@app.route('/add_item', methods=('GET', 'POST'))
@login_required
def add_item():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการเพิ่มสินค้า', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    current_year = get_bkk_time().year
    form_data = None
    active_tab = request.args.get('tab', 'tire')

    all_promotions = database.get_all_promotions(conn, include_inactive=False)

    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        form_data = request.form

        current_user_id = current_user.id if current_user.is_authenticated else None

        if submit_type == 'add_tire':
            brand = request.form['brand'].strip().lower()
            model = request.form['model'].strip().lower()
            size = request.form['size'].strip()
            quantity = request.form['quantity']

            cost_sc = request.form.get('cost_sc')
            price_per_item = request.form['price_per_item']

            cost_dunlop = request.form.get('cost_dunlop')
            cost_online = request.form.get('cost_online')
            wholesale_price1 = request.form.get('wholesale_price1')
            wholesale_price2 = request.form.get('wholesale_price2')

            promotion_id = request.form.get('promotion_id')
            if promotion_id == 'none' or not promotion_id:
                promotion_id_db = None
            else:
                promotion_id_db = int(promotion_id)

            year_of_manufacture = request.form.get('year_of_manufacture')

            if not brand or not model or not size or not quantity or not price_per_item:
                flash('กรุณากรอกข้อมูลยางให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)

            try:
                quantity = int(quantity)
                price_per_item = float(price_per_item)

                cost_sc = float(cost_sc) if cost_sc and cost_sc.strip() else None
                cost_dunlop = float(cost_dunlop) if cost_dunlop and cost_dunlop.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None
                
                year_of_manufacture = year_of_manufacture.strip() if year_of_manufacture and year_of_manufacture.strip() else None

                database.add_tire(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, 
                                  wholesale_price1, wholesale_price2, price_per_item, 
                                  promotion_id_db, 
                                  year_of_manufacture,
                                  user_id=current_user_id)
                flash('เพิ่มยางใหม่สำเร็จ!', 'success')
                return redirect(url_for('add_item', tab='tire'))

            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ยางยี่ห้อ {brand} รุ่น {model} เบอร์ {size} มีอยู่ในระบบแล้ว หากต้องการแก้ไข กรุณาไปที่หน้าสต็อก', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มยาง: {e}', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)

        elif submit_type == 'add_wheel':
            brand = request.form['brand'].strip().lower()
            model = request.form['model'].strip().lower()
            diameter = request.form['diameter']
            pcd = request.form['pcd'].strip()
            width = request.form['width']
            quantity = request.form['quantity']

            cost = request.form.get('cost')
            retail_price = request.form['retail_price']
            et = request.form.get('et')
            color = request.form.get('color', '').strip()
            cost_online = request.form.get('cost_online')
            wholesale_price1 = request.form.get('wholesale_price1')
            wholesale_price2 = request.form.get('wholesale_price2')
            image_file = request.files.get('image_file')

            if not brand or not model or not pcd or not diameter or not width or not quantity or not retail_price:
                flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)

            try:
                diameter = float(diameter)
                width = float(width)
                quantity = int(quantity)
                retail_price = float(retail_price)

                cost = float(cost) if cost and cost.strip() else None
                et = int(et) if et and et.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None

                image_url = None
                
                if image_file and image_file.filename != '':
                    if allowed_image_file(image_file.filename):
                        try:
                            upload_result = cloudinary.uploader.upload(image_file)
                            image_url = upload_result['secure_url']
                            
                        except Exception as e:
                            flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพไปยัง Cloudinary: {e}', 'danger')
                            active_tab = 'wheel'
                            return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                    else:
                        flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                        active_tab = 'wheel'
                        return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                
                database.add_wheel(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, user_id=current_user_id)
                flash('เพิ่มแม็กใหม่สำเร็จ!', 'success')
                return redirect(url_for('add_item', tab='wheel'))

            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'แม็กยี่ห้อ {brand} ลาย {model} ขอบ {diameter} รู {pcd} กว้าง {width} มีอยู่ในระบบแล้ว หากต้องการแก้ไข กรุณาไปที่หน้าสต็อก', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มแม็ก: {e}', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
    
    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)

@app.route('/edit_tire/<int:tire_id>', methods=('GET', 'POST'))
@login_required
def edit_tire(tire_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลยาง', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    tire = database.get_tire(conn, tire_id)
    current_year = get_bkk_time().year

    if tire is None:
        flash('ไม่พบยางที่ระบุ', 'danger')
        return redirect(url_for('index', tab='tires'))

    all_promotions = database.get_all_promotions(conn, include_inactive=True)

    if request.method == 'POST':
        brand = request.form['brand'].strip().lower()
        model = request.form['model'].strip().lower()
        size = request.form['size'].strip()

        cost_sc = request.form.get('cost_sc')
        price_per_item = request.form['price_per_item']

        cost_dunlop = request.form.get('cost_dunlop')
        cost_online = request.form.get('cost_online')
        wholesale_price1 = request.form.get('wholesale_price1')
        wholesale_price2 = request.form.get('wholesale_price2')

        promotion_id = request.form.get('promotion_id')
        if promotion_id == 'none' or not promotion_id:
            promotion_id_db = None
        else:
            promotion_id_db = int(promotion_id)

        year_of_manufacture = request.form.get('year_of_manufacture')

        if not brand or not model or not size or not str(price_per_item):
            flash('กรุณากรอกข้อมูลยางให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
        else:
            try:
                price_per_item = float(price_per_item)

                cost_sc = float(cost_sc) if cost_sc and cost_sc.strip() else None
                cost_dunlop = float(cost_dunlop) if cost_dunlop and cost_dunlop.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None
                
                year_of_manufacture = year_of_manufacture.strip() if year_of_manufacture and year_of_manufacture.strip() else None

                database.update_tire(conn, tire_id, brand, model, size, cost_sc, cost_dunlop, cost_online, 
                                     wholesale_price1, wholesale_price2, price_per_item, 
                                     promotion_id_db, 
                                     year_of_manufacture)
                flash('แก้ไขข้อมูลยางสำเร็จ!', 'success')
                return redirect(url_for('index', tab='tires'))
            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ยางยี่ห้อ {brand} รุ่น {model} เบอร์ {size} นี้มีอยู่ในระบบแล้วภายใต้ ID อื่น โปรดตรวจสอบ', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลยาง: {e}', 'danger')

    return render_template('edit_tire.html', tire=tire, current_year=current_year, all_promotions=all_promotions)

@app.route('/delete_tire/<int:tire_id>', methods=('POST',))
@login_required
def delete_tire(tire_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการลบยาง', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    tire = database.get_tire(conn, tire_id)

    if tire is None:
        flash('ไม่พบยางที่ระบุ', 'danger')
    elif tire['quantity'] > 0:
        flash('ไม่สามารถลบยางได้เนื่องจากยังมีสต็อกเหลืออยู่. กรุณาปรับสต็อกให้เป็น 0 ก่อน.', 'danger')
        return redirect(url_for('index', tab='tires'))
    else:
        try:
            database.delete_tire(conn, tire_id)
            flash('ทำเครื่องหมายยางว่าถูกลบสำเร็จ!', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการทำเครื่องหมายยางว่าถูกลบ: {e}', 'danger')
    
    return redirect(url_for('index', tab='tires'))

# --- Wheel Routes (Main item editing) ---
@app.route('/wheel_detail/<int:wheel_id>')
@login_required
def wheel_detail(wheel_id):
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)
    fitments = database.get_wheel_fitments(conn, wheel_id)
    current_year = get_bkk_time().year

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
        return redirect(url_for('index', tab='wheels'))
    
    return render_template('wheel_detail.html', wheel=wheel, fitments=fitments, current_year=current_year)

@app.route('/edit_wheel/<int:wheel_id>', methods=('GET', 'POST'))
@login_required
def edit_wheel(wheel_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลแม็ก', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)
    current_year = get_bkk_time().year

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
        return redirect(url_for('index', tab='wheels'))

    if request.method == 'POST':
        brand = request.form['brand'].strip()
        model = request.form['model'].strip()
        diameter = float(request.form['diameter'])
        pcd = request.form['pcd'].strip()
        width = float(request.form['width'])
        et = request.form.get('et')
        color = request.form.get('color', '').strip()
        cost = request.form.get('cost')
        cost_online = request.form.get('cost_online')
        wholesale_price1 = request.form.get('wholesale_price1')
        wholesale_price2 = request.form.get('wholesale_price2')
        retail_price = float(request.form['retail_price'])
        image_file = request.files.get('image_file')

        if not brand or not model or not pcd or not str(diameter) or not str(width) or not str(retail_price):
            flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
        else:
            try:
                et = int(et) if et else None
                cost_online = float(cost_online) if cost_online else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 else None
                cost = float(cost) if cost and cost.strip() else None

                current_image_url = wheel['image_filename']
                
                if image_file and image_file.filename != '':
                    if allowed_image_file(image_file.filename):
                        try:
                            upload_result = cloudinary.uploader.upload(image_file)
                            new_image_url = upload_result['secure_url']
                            
                            if current_image_url and "res.cloudinary.com" in current_image_url:
                                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                                if public_id_match:
                                    public_id = public_id_match.group(1)
                                    try:
                                        cloudinary.uploader.destroy(public_id)
                                    except Exception as e:
                                        print(f"Error deleting old image from Cloudinary: {e}")
                            
                            current_image_url = new_image_url
                        
                        except Exception as e:
                            flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพไปยัง Cloudinary: {e}', 'danger')
                            return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)
                    else:
                        flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                        return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)

                database.update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, current_image_url)
                flash('แก้ไขข้อมูลแม็กสำเร็จ!', 'success')
                return redirect(url_for('wheel_detail', wheel_id=wheel_id))
            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'แม็กยี่ห้อ {brand} ลาย {model} ขอบ {diameter} รู {pcd} กว้าง {width} นี้มีอยู่ในระบบแล้วภายใต้ ID อื่น โปรดตรวจสอบ', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลแม็ก: {e}', 'danger')

    return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)

@app.route('/delete_wheel/<int:wheel_id>', methods=('POST',))
@login_required
def delete_wheel(wheel_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการลบแม็ก', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
    elif wheel['quantity'] > 0:
        flash('ไม่สามารถลบแม็กได้เนื่องจากยังมีสต็อกเหลืออยู่. กรุณาปรับสต็อกให้เป็น 0 ก่อน.', 'danger')
        return redirect(url_for('index', tab='wheels'))
    else:
        try:
            database.delete_wheel(conn, wheel_id)
            flash('ลบแม็กสำเร็จ!', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบแม็ก: {e}', 'danger')
    
    return redirect(url_for('index', tab='wheels'))

@app.route('/add_fitment/<int:wheel_id>', methods=('POST',))
@login_required
def add_fitment(wheel_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการเพิ่มข้อมูลการรองรับรถยนต์', 'danger')
        return redirect(url_for('wheel_detail', wheel_id=wheel_id))
    conn = get_db()
    brand = request.form['brand'].strip()
    model = request.form['model'].strip()
    year_start = request.form['year_start'].strip()
    year_end = request.form.get('year_end', '').strip()

    if not brand or not model or not year_start:
        flash('กรุณากรอกข้อมูลการรองรับรถยนต์ให้ครบถ้วน', 'danger')
    else:
        try:
            year_start = int(year_start)
            year_end = int(year_end) if year_end else None

            if year_end and year_end < year_start:
                flash('ปีสิ้นสุดต้องไม่น้อยกว่าปีเริ่มต้น', 'danger')
            else:
                database.add_wheel_fitment(conn, wheel_id, brand, model, year_start, year_end)
                flash('เพิ่มข้อมูลการรองรับสำเร็จ!', 'success')
        except ValueError:
            flash('ข้อมูลปีไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการเพิ่มข้อมูลการรองรับ: {e}', 'danger')
    
    return redirect(url_for('wheel_detail', wheel_id=wheel_id))

@app.route('/delete_fitment/<int:fitment_id>/<int:wheel_id>', methods=('POST',))
@login_required
def delete_fitment(fitment_id, wheel_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการลบข้อมูลการรองรับรถยนต์', 'danger')
        return redirect(url_for('wheel_detail', wheel_id=wheel_id))
    conn = get_db()
    try:
        database.delete_wheel_fitment(conn, fitment_id)
        flash('ลบข้อมูลการรองรับสำเร็จ!', 'success')
    except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบข้อมูลการรองรับ: {e}', 'danger')
    
    return redirect(url_for('wheel_detail', wheel_id=wheel_id))


# --- Stock Movement Routes (Movement editing) ---
@app.route('/stock_movement', methods=('GET', 'POST'))
@login_required
def stock_movement():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการจัดการการเคลื่อนไหวสต็อก', 'danger')
        return redirect(url_for('index'))
    conn = get_db()

    tires = database.get_all_tires(conn)
    wheels = database.get_all_wheels(conn)
    
    active_tab = request.args.get('tab', 'tire_movements') 

    # --- สำหรับ Tire Movements History ---
    tire_movements_query = """
        SELECT tm.*, t.brand, t.model, t.size, u.username AS user_username
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        LEFT JOIN users u ON tm.user_id = u.id
        ORDER BY tm.timestamp DESC LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor_tire = conn.cursor()
        cursor_tire.execute(tire_movements_query)
        tire_movements_history_raw = cursor_tire.fetchall()
    else:
        tire_movements_history_raw = conn.execute(tire_movements_query).fetchall()

    processed_tire_movements_history = []
    for movement in tire_movements_history_raw:
        movement_data = movement
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_tire_movements_history.append(movement_data)
    tire_movements_history = processed_tire_movements_history


    # --- สำหรับ Wheel Movements History ---
    wheel_movements_query = """
        SELECT wm.*, w.brand, w.model, w.diameter, u.username AS user_username
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        LEFT JOIN users u ON wm.user_id = u.id
        ORDER BY wm.timestamp DESC LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor_wheel = conn.cursor()
        cursor_wheel.execute(wheel_movements_query)
        wheel_movements_history_raw = cursor_wheel.fetchall()
    else:
        wheel_movements_history_raw = conn.execute(wheel_movements_query).fetchall()

    processed_wheel_movements_history = []
    for movement in wheel_movements_history_raw:
        movement_data = movement
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_wheel_movements_history.append(movement_data)
    wheel_movements_history = processed_wheel_movements_history

    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        active_tab_on_error = 'tire_movements' if submit_type == 'tire_movement' else 'wheel_movements'

        item_id_key = ''
        quantity_form_key = ''
        if submit_type == 'tire_movement':
            item_id_key = 'tire_id'
            quantity_form_key = 'quantity'
        elif submit_type == 'wheel_movement':
            item_id_key = 'wheel_id'
            quantity_form_key = 'quantity'
        else:
            flash('ประเภทการส่งฟอร์มไม่ถูกต้อง', 'danger')
            return redirect(url_for('stock_movement'))
        
        if quantity_form_key not in request.form or not request.form[quantity_form_key].strip():
            flash('กรุณากรอกจำนวนที่เปลี่ยนแปลงให้ถูกต้อง', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
        
        try:
            item_id = request.form[item_id_key]
            move_type = request.form['type']
            quantity_change = int(request.form[quantity_form_key])
            notes = request.form.get('notes', '').strip()
            bill_image_file = request.files.get('bill_image')

            bill_image_url_to_db = None
            
            if bill_image_file and bill_image_file.filename != '':
                if allowed_image_file(bill_image_file.filename):
                    try:
                        upload_result = cloudinary.uploader.upload(bill_image_file)
                        bill_image_url_to_db = upload_result['secure_url']
                        
                    except Exception as e:
                        flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิลไปยัง Cloudinary: {e}', 'danger')
                        return redirect(url_for('stock_movement', tab=active_tab_on_error))
                else:
                    flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    return redirect(url_for('stock_movement', tab=active_tab_on_error))

            if quantity_change <= 0:
                flash('จำนวนที่เปลี่ยนแปลงต้องมากกว่า 0', 'danger')
                return redirect(url_for('stock_movement', tab=active_tab_on_error))
            
            current_user_id = current_user.id if current_user.is_authenticated else None

            if submit_type == 'tire_movement':
                tire_id = int(item_id)
                current_tire = database.get_tire(conn, tire_id)
                if current_tire is None:
                    flash('ไม่พบยางที่ระบุ', 'danger')
                    return redirect(url_for('stock_movement', tab=active_tab_on_error))
                
                new_quantity = current_tire['quantity']
                if move_type == 'IN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกยางไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} เส้น.', 'danger')
                        return redirect(url_for('stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change
                
                database.update_tire_quantity(conn, tire_id, new_quantity)
                database.add_tire_movement(conn, tire_id, move_type, quantity_change, new_quantity, notes, bill_image_url_to_db, user_id=current_user_id)
                flash(f'บันทึกการเคลื่อนไหวสต็อกยางสำเร็จ! คงเหลือ: {new_quantity} เส้น', 'success')
                return redirect(url_for('stock_movement', tab='tire_movements'))

            elif submit_type == 'wheel_movement':
                wheel_id = int(item_id)
                current_wheel = database.get_wheel(conn, wheel_id)
                if current_wheel is None:
                    flash('ไม่พบแม็กที่ระบุ', 'danger')
                    return redirect(url_for('stock_movement', tab=active_tab_on_error))
                
                new_quantity = current_wheel['quantity']
                if move_type == 'IN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกแม็กไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} วง.', 'danger')
                        return redirect(url_for('stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change
                
                database.update_wheel_quantity(conn, wheel_id, new_quantity)
                database.add_wheel_movement(conn, wheel_id, move_type, quantity_change, new_quantity, notes, bill_image_url_to_db, user_id=current_user_id)
                flash(f'บันทึกการเคลื่อนไหวสต็อกแม็กสำเร็จ! คงเหลือ: {new_quantity} วง', 'success')
                return redirect(url_for('stock_movement', tab='wheel_movements'))

        except ValueError:
            flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการบันทึกการเคลื่อนไหวสต็อก: {e}', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
    
    return render_template('stock_movement.html', 
                           tires=tires, 
                           wheels=wheels, 
                           active_tab=active_tab,
                           tire_movements=tire_movements_history, 
                           wheel_movements=wheel_movements_history)

@app.route('/edit_tire_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_tire_movement(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกยาง', 'danger')
        return redirect(url_for('daily_stock_report'))

    conn = get_db()
    movement = database.get_tire_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        return redirect(url_for('daily_stock_report'))

    movement_data = movement
    movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])


    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement_data['image_filename']
        bill_image_url_to_db = current_image_url

        if delete_existing_image:
            if current_image_url and "res.cloudinary.com" in current_image_url:
                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                if public_id_match:
                    public_id = public_id_match.group(1)
                    try:
                        cloudinary.uploader.destroy(public_id)
                    except Exception as e:
                        print(f"Error deleting old tire movement image from Cloudinary: {e}")
            bill_image_url_to_db = None

        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    upload_result = cloudinary.uploader.upload(bill_image_file)
                    new_image_url = upload_result['secure_url']
                    bill_image_url_to_db = new_image_url
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิลไปยัง Cloudinary: {e}', 'danger')
                    return render_template('edit_tire_movement.html', movement=movement_data)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                return render_template('edit_tire_movement.html', movement=movement_data)

        try:
            database.update_tire_movement(conn, movement_id, new_notes, bill_image_url_to_db)
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกยางสำเร็จ!', 'success')
            return redirect(url_for('daily_stock_report'))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')

    return render_template('edit_tire_movement.html', movement=movement_data)

@app.route('/edit_wheel_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_wheel_movement(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกแม็ก', 'danger')
        return redirect(url_for('daily_stock_report'))

    conn = get_db()
    movement = database.get_wheel_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        return redirect(url_for('daily_stock_report'))

    movement_data = movement
    movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])

    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement_data['image_filename']
        bill_image_url_to_db = current_image_url

        if delete_existing_image:
            if current_image_url and "res.cloudinary.com" in current_image_url:
                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                if public_id_match:
                    public_id = public_id_match.group(1)
                    try:
                        cloudinary.uploader.destroy(public_id)
                    except Exception as e:
                        print(f"Error deleting old wheel movement image from Cloudinary: {e}")
            bill_image_url_to_db = None

        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    upload_result = cloudinary.uploader.upload(bill_image_file)
                    new_image_url = upload_result['secure_url']
                    bill_image_url_to_db = new_image_url
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิลไปยัง Cloudinary: {e}', 'danger')
                    return render_template('edit_wheel_movement.html', movement=movement_data)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                return render_template('edit_wheel_movement.html', movement=movement_data)

        try:
            database.update_wheel_movement(conn, movement_id, new_notes, bill_image_url_to_db)
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกแม็กสำเร็จ!', 'success')
            return redirect(url_for('daily_stock_report'))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')

    return render_template('edit_wheel_movement.html', movement=movement_data)

# --- daily_stock_report ---
@app.route('/daily_stock_report')
@login_required
def daily_stock_report():
    conn = get_db()
    
    report_date_str = request.args.get('date')
    
    report_datetime_obj = None

    if report_date_str:
        try:
            report_datetime_obj = BKK_TZ.localize(datetime.strptime(report_date_str, '%Y-%m-%d'))
            display_date_str = report_datetime_obj.strftime('%d %b %Y')
        except ValueError:
            flash("รูปแบบวันที่ไม่ถูกต้อง กรุณาใช้YYYY-MM-DD", "danger")
            report_datetime_obj = get_bkk_time()
            display_date_str = report_datetime_obj.strftime('%d %b %Y')
    else:
        report_datetime_obj = get_bkk_time()
        display_date_str = report_datetime_obj.strftime('%d %b %Y')

    report_date = report_datetime_obj.date()
    sql_date_filter = report_date.strftime('%Y-%m-%d')
    sql_date_filter_end_of_day = report_datetime_obj.replace(hour=23, minute=59, second=59).isoformat()

    # --- Tire Report Data ---
    tire_movements_query_today = f"""
        SELECT
            tm.id, tm.timestamp, tm.type, tm.quantity_change, tm.image_filename, tm.notes,
            t.id AS tire_main_id, t.brand, t.model, t.size,
            u.username AS user_username
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        LEFT JOIN users u ON tm.user_id = u.id
        WHERE {database.get_sql_date_format_for_query('tm.timestamp')} = %s
        ORDER BY tm.timestamp DESC
    """ # MODIFIED: ORDER BY tm.timestamp DESC
    if "psycopg2" in str(type(conn)):
        cursor = conn.cursor()
        cursor.execute(tire_movements_query_today, (sql_date_filter,))
        tire_movements_raw_today = cursor.fetchall()
    else:
        tire_movements_raw_today = conn.execute(tire_movements_query_today.replace('%s', '?'), (sql_date_filter,)).fetchall()

    processed_tire_movements_raw_today = []
    for movement in tire_movements_raw_today:
        movement_data = dict(movement)
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_tire_movements_raw_today.append(movement_data)
    tire_movements_raw = processed_tire_movements_raw_today


    tire_quantities_before_report = defaultdict(int)
    tire_ids_involved = set()
    for movement in tire_movements_raw:
        tire_ids_involved.add(movement['tire_main_id'])

    day_before_report = report_datetime_obj.replace(hour=0, minute=0, second=0) - timedelta(microseconds=1)
    day_before_report_iso = day_before_report.isoformat()

    distinct_tire_ids_query_all_history = f"""
        SELECT DISTINCT tire_id
        FROM tire_movements
        WHERE timestamp <= %s
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(distinct_tire_ids_query_all_history, (sql_date_filter_end_of_day,))
    else:
        cursor.execute(distinct_tire_ids_query_all_history.replace('%s', '?'), (sql_date_filter_end_of_day,))
    
    for row in cursor.fetchall():
        tire_ids_involved.add(row['tire_id'])


    for tire_id in tire_ids_involved:
        history_query_up_to_day_before = f"""
            SELECT type, quantity_change
            FROM tire_movements
            WHERE tire_id = %s AND timestamp <= %s
            ORDER BY timestamp ASC
        """
        if "psycopg2" in str(type(conn)):
            cursor.execute(history_query_up_to_day_before, (tire_id, day_before_report_iso))
        else:
            cursor.execute(history_query_up_to_day_before.replace('%s', '?'), (tire_id, day_before_report_iso,))
        
        calculated_qty_before_day = 0
        for move in cursor.fetchall():
            if move['type'] == 'IN':
                calculated_qty_before_day += move['quantity_change']
            elif move['type'] == 'OUT':
                calculated_qty_before_day -= move['quantity_change']
        tire_quantities_before_report[tire_id] = calculated_qty_before_day

    sorted_detailed_tire_report = []
    detailed_tire_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'remaining_quantity': 0, 'tire_main_id': None, 'brand': '', 'model': '', 'size': ''})

    for movement in tire_movements_raw:
        key = (movement['brand'], movement['model'], movement['size'])
        tire_id = movement['tire_main_id']

        if key not in detailed_tire_report:
            detailed_tire_report[key]['tire_main_id'] = tire_id
            detailed_tire_report[key]['brand'] = movement['brand']
            detailed_tire_report[key]['model'] = movement['model']
            detailed_tire_report[key]['size'] = movement['size']
            detailed_tire_report[key]['remaining_quantity'] = tire_quantities_before_report[tire_id]

        if movement['type'] == 'IN':
            detailed_tire_report[key]['IN'] += movement['quantity_change']
            detailed_tire_report[key]['remaining_quantity'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            detailed_tire_report[key]['OUT'] += movement['quantity_change']
            detailed_tire_report[key]['remaining_quantity'] -= movement['quantity_change']
    
    for tire_id, qty in tire_quantities_before_report.items():
        if not any(item['tire_main_id'] == tire_id for item in tire_movements_raw):
            tire_info = database.get_tire(conn, tire_id)
            if tire_info and not tire_info['is_deleted']:
                key = (tire_info['brand'], tire_info['model'], tire_info['size'])
                if key not in detailed_tire_report:
                    detailed_tire_report[key]['tire_main_id'] = tire_id
                    detailed_tire_report[key]['brand'] = tire_info['brand']
                    detailed_tire_report[key]['model'] = tire_info['model']
                    detailed_tire_report[key]['size'] = tire_info['size']
                    detailed_tire_report[key]['remaining_quantity'] = qty


    tire_brand_summaries = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'current_quantity_sum': 0})
    sorted_unique_tire_items = sorted(detailed_tire_report.items(), key=lambda x: x[0])

    last_brand = None
    for (brand, model, size), data in sorted_unique_tire_items:
        if last_brand is not None and brand != last_brand:
            summary_data = tire_brand_summaries[last_brand]
            sorted_detailed_tire_report.append({
                'is_summary': True,
                'brand': last_brand,
                'IN': summary_data['IN'],
                'OUT': summary_data['OUT'],
                'remaining_quantity': summary_data['current_quantity_sum']
            })
        
        sorted_detailed_tire_report.append({
            'is_summary': False,
            'brand': brand,
            'model': model,
            'size': size,
            'IN': data['IN'],
            'OUT': data['OUT'],
            'remaining_quantity': data['remaining_quantity']
        })

        tire_brand_summaries[brand]['IN'] += data['IN']
        tire_brand_summaries[brand]['OUT'] += data['OUT']
        tire_brand_summaries[brand]['current_quantity_sum'] += data['remaining_quantity']
        last_brand = brand
    
    if last_brand is not None:
        summary_data = tire_brand_summaries[last_brand]
        sorted_detailed_tire_report.append({
            'is_summary': True,
            'brand': last_brand,
            'IN': summary_data['IN'],
            'OUT': summary_data['OUT'],
            'remaining_quantity': summary_data['current_quantity_sum']
        })


    # --- Wheel Report Data ---
    wheel_movements_query_today = f"""
        SELECT
            wm.id, wm.timestamp, wm.type, wm.quantity_change, wm.image_filename, wm.notes,
            w.id AS wheel_main_id, w.brand, w.model, w.diameter, w.pcd, w.width,
            u.username AS user_username
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        LEFT JOIN users u ON wm.user_id = u.id
        WHERE {database.get_sql_date_format_for_query('wm.timestamp')} = %s
        ORDER BY wm.timestamp DESC
    """ # MODIFIED: ORDER BY wm.timestamp DESC
    if "psycopg2" in str(type(conn)):
        cursor = conn.cursor()
        cursor.execute(wheel_movements_query_today, (sql_date_filter,))
        wheel_movements_raw_today = cursor.fetchall()
    else:
        wheel_movements_raw_today = conn.execute(wheel_movements_query_today.replace('%s', '?'), (sql_date_filter,)).fetchall()

    processed_wheel_movements_raw_today = []
    for movement in wheel_movements_raw_today:
        movement_data = dict(movement)
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_wheel_movements_raw_today.append(movement_data)
    wheel_movements_raw = processed_wheel_movements_raw_today


    wheel_quantities_before_report = defaultdict(int)
    wheel_ids_involved = set()
    for movement in wheel_movements_raw:
        wheel_ids_involved.add(movement['wheel_main_id'])

    day_before_report = report_datetime_obj.replace(hour=0, minute=0, second=0) - timedelta(microseconds=1)
    day_before_report_iso = day_before_report.isoformat()

    distinct_wheel_ids_query_all_history = f"""
        SELECT DISTINCT wheel_id
        FROM wheel_movements
        WHERE timestamp <= %s
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(distinct_wheel_ids_query_all_history, (sql_date_filter_end_of_day,))
    else:
        cursor.execute(distinct_wheel_ids_query_all_history.replace('%s', '?'), (sql_date_filter_end_of_day,))
    
    for row in cursor.fetchall():
        wheel_ids_involved.add(row['wheel_id'])


    for wheel_id in wheel_ids_involved:
        history_query_up_to_day_before = f"""
            SELECT type, quantity_change
            FROM wheel_movements
            WHERE wheel_id = %s AND timestamp <= %s
            ORDER BY timestamp ASC
        """
        if "psycopg2" in str(type(conn)):
            cursor.execute(history_query_up_to_day_before, (wheel_id, day_before_report_iso))
        else:
            cursor.execute(history_query_up_to_day_before.replace('%s', '?'), (wheel_id, day_before_report_iso,))
        
        calculated_qty_before_day = 0
        for move in cursor.fetchall():
            if move['type'] == 'IN':
                calculated_qty_before_day += move['quantity_change']
            elif move['type'] == 'OUT':
                calculated_qty_before_day -= move['quantity_change']
        wheel_quantities_before_report[wheel_id] = calculated_qty_before_day


    sorted_detailed_wheel_report = []
    detailed_wheel_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'remaining_quantity': 0, 'wheel_main_id': None, 'brand': '', 'model': '', 'diameter': None, 'pcd': '', 'width': None})

    for movement in wheel_movements_raw:
        key = (movement['brand'], movement['model'], movement['diameter'], movement['pcd'], movement['width'])
        wheel_id = movement['wheel_main_id']

        if key not in detailed_wheel_report:
            detailed_wheel_report[key]['wheel_main_id'] = wheel_id
            detailed_wheel_report[key]['brand'] = movement['brand']
            detailed_wheel_report[key]['model'] = movement['model']
            detailed_wheel_report[key]['diameter'] = movement['diameter']
            detailed_wheel_report[key]['pcd'] = movement['pcd']
            detailed_wheel_report[key]['width'] = movement['width']
            detailed_wheel_report[key]['remaining_quantity'] = wheel_quantities_before_report[wheel_id]

        if movement['type'] == 'IN':
            detailed_wheel_report[key]['IN'] += movement['quantity_change']
            detailed_wheel_report[key]['remaining_quantity'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            detailed_wheel_report[key]['OUT'] += movement['quantity_change']
            detailed_wheel_report[key]['remaining_quantity'] -= movement['quantity_change']
    
    for wheel_id, qty in wheel_quantities_before_report.items():
        if not any(item['wheel_main_id'] == wheel_id for item in wheel_movements_raw):
            wheel_info = database.get_wheel(conn, wheel_id)
            if wheel_info and not wheel_info['is_deleted']:
                key = (wheel_info['brand'], wheel_info['model'], wheel_info['diameter'], wheel_info['pcd'], wheel_info['width'])
                if key not in detailed_wheel_report:
                    detailed_wheel_report[key]['wheel_main_id'] = wheel_id
                    detailed_wheel_report[key]['brand'] = wheel_info['brand']
                    detailed_wheel_report[key]['model'] = wheel_info['model']
                    detailed_wheel_report[key]['diameter'] = wheel_info['diameter']
                    detailed_wheel_report[key]['pcd'] = wheel_info['pcd']
                    detailed_wheel_report[key]['width'] = wheel_info['width']
                    detailed_wheel_report[key]['remaining_quantity'] = qty


    wheel_brand_summaries = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'current_quantity_sum': 0})
    sorted_unique_wheel_items = sorted(detailed_wheel_report.items(), key=lambda x: x[0])

    last_brand = None
    for (brand, model, diameter, pcd, width), data in sorted_unique_wheel_items:
        if last_brand is not None and brand != last_brand:
            summary_data = wheel_brand_summaries[last_brand]
            sorted_detailed_wheel_report.append({
                'is_summary': True,
                'brand': last_brand,
                'IN': summary_data['IN'],
                'OUT': summary_data['OUT'],
                'remaining_quantity': summary_data['current_quantity_sum']
            })
        
        sorted_detailed_wheel_report.append({
            'is_summary': False,
            'brand': brand,
            'model': model,
            'diameter': diameter,
            'pcd': pcd,
            'width': width,
            'IN': data['IN'],
            'OUT': data['OUT'],
            'remaining_quantity': data['remaining_quantity']
        })

        wheel_brand_summaries[brand]['IN'] += data['IN']
        wheel_brand_summaries[brand]['OUT'] += data['OUT']
        wheel_brand_summaries[brand]['current_quantity_sum'] += data['remaining_quantity']
        last_brand = brand
    
    if last_brand is not None:
        summary_data = wheel_brand_summaries[last_brand]
        sorted_detailed_wheel_report.append({
            'is_summary': True,
            'brand': last_brand,
            'IN': summary_data['IN'],
            'OUT': summary_data['OUT'],
            'remaining_quantity': summary_data['current_quantity_sum']
        })

    tire_total_in = sum(item['IN'] for item in sorted_detailed_tire_report if not item['is_summary'])
    tire_total_out = sum(item['OUT'] for item in sorted_detailed_tire_report if not item['is_summary'])
    
    tire_total_remaining_for_report_date = 0
    query_total_before_tires = f"""
        SELECT SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END)
        FROM tire_movements
        WHERE timestamp < %s
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(query_total_before_tires, (report_datetime_obj.strftime('%Y-%m-%d %H:%M:%S%z'),))
    else:
        cursor.execute(query_total_before_tires.replace('%s', '?'), (report_datetime_obj.strftime('%Y-%m-%d %H:%M:%S.%f'),))
    
    initial_total_tires = cursor.fetchone()[0] or 0
    
    tire_total_remaining_for_report_date = initial_total_tires + tire_total_in - tire_total_out


    wheel_total_in = sum(item['IN'] for item in sorted_detailed_wheel_report if not item['is_summary'])
    wheel_total_out = sum(item['OUT'] for item in sorted_detailed_wheel_report if not item['is_summary'])

    wheel_total_remaining_for_report_date = 0
    query_total_before_wheels = f"""
        SELECT SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END)
        FROM wheel_movements
        WHERE timestamp < %s
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(query_total_before_wheels, (report_datetime_obj.strftime('%Y-%m-%d %H:%M:%S%z'),))
    else:
        cursor.execute(query_total_before_wheels.replace('%s', '?'), (report_datetime_obj.strftime('%Y-%m-%d %H:%M:%S.%f'),))
    
    initial_total_wheels = cursor.fetchone()[0] or 0

    wheel_total_remaining_for_report_date = initial_total_wheels + wheel_total_in - wheel_total_out


    # Calculate yesterday and tomorrow dates using the datetime object
    yesterday_date_calc = report_datetime_obj - timedelta(days=1)
    tomorrow_date_calc = report_datetime_obj + timedelta(days=1)
    
    return render_template('daily_stock_report.html',
                           display_date_str=display_date_str,
                           report_date_obj=report_date,
                           report_date_param=report_date.strftime('%Y-%m-%d'),
                           yesterday_date_param=yesterday_date_calc.strftime('%Y-%m-%d'),
                           tomorrow_date_param=tomorrow_date_calc.strftime('%Y-%m-%d'),
                           
                           tire_report=sorted_detailed_tire_report,
                           wheel_report=sorted_detailed_wheel_report,
                           tire_total_in=tire_total_in,
                           tire_total_out=tire_total_out,
                           tire_total_remaining=tire_total_remaining_for_report_date, 
                           wheel_total_in=wheel_total_in,
                           wheel_total_out=wheel_total_out,
                           wheel_total_remaining=wheel_total_remaining_for_report_date, 
                           
                           tire_movements_raw=tire_movements_raw,
                           wheel_movements_raw=wheel_movements_raw
                          )

# --- Import/Export Routes ---
@app.route('/export_import', methods=('GET', 'POST'))
@login_required
def export_import():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการนำเข้า/ส่งออกข้อมูล', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    active_tab = request.args.get('tab', 'tires_excel')
    return render_template('export_import.html', active_tab=active_tab)

@app.route('/export_tires_action')
@login_required
def export_tires_action():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการส่งออกข้อมูลยาง', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))
    conn = get_db()
    tires = database.get_all_tires(conn)

    if not tires:
        flash('ไม่มีข้อมูลยางให้ส่งออก', 'warning')
        return redirect(url_for('export_import', tab='tires_excel'))

    data = []
    for tire in tires:
        data.append({
            'ID': tire['id'],
            'ยี่ห้อ': tire['brand'],
            'รุ่นยาง': tire['model'],
            'เบอร์ยาง': tire['size'],
            'สต็อก': tire['quantity'],
            'ทุน SC': tire['cost_sc'],
            'ทุน Dunlop': tire['cost_dunlop'],
            'ทุน Online': tire['cost_online'],
            'ราคาขายส่ง 1': tire['wholesale_price1'],
            'ราคาขายส่ง 2': tire['wholesale_price2'],
            'ราคาต่อเส้น': tire['price_per_item'],
            'ID โปรโมชัน': tire['promotion_id'],
            'ชื่อโปรโมชัน': tire['promo_name'],
            'ประเภทโปรโมชัน': tire['promo_type'],
            'ค่าโปรโมชัน Value1': tire['promo_value1'],
            'ค่าโปรโมชัน Value2': tire['promo_value2'],
            'รายละเอียดโปรโมชัน': tire['display_promo_description_text'],
            'ราคาโปรโมชันคำนวณ(เส้น)': tire['display_promo_price_per_item'],
            'ราคาโปรโมชันคำนวณ(4เส้น)': tire['display_price_for_4'],
            'ปีผลิต': tire['year_of_manufacture']
        })

    df = pd.DataFrame(data)

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Tires Stock')
    writer.close()
    output.seek(0)

    return send_file(output, download_name='tire_stock.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/import_tires_action', methods=('POST',))
@login_required
def import_tires_action():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการนำเข้าข้อมูลยาง', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))
    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))
    
    if file and allowed_excel_file(file.filename):
        try:
            df = pd.read_excel(file)
            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            expected_tire_cols = [
                'ยี่ห้อ', 'รุ่นยาง', 'เบอร์ยาง', 'สต็อก', 'ทุน SC', 'ทุน Dunlop', 'ทุน Online',
                'ราคาขายส่ง 1', 'ราคาขายส่ง 2', 'ราคาต่อเส้น', 'ID โปรโมชัน', 'ปีผลิต' 
            ]
            
            if not all(col in df.columns for col in expected_tire_cols):
                missing_cols = [col for col in expected_tire_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                return redirect(url_for('export_import', tab='tires_excel'))

            for index, row in df.iterrows():
                try:
                    brand = str(row.get('ยี่ห้อ', '')).strip().lower()
                    model = str(row.get('รุ่นยาง', '')).strip().lower()
                    size = str(row.get('เบอร์ยาง', '')).strip()
                    
                    if not brand or not model or not size:
                        raise ValueError("ข้อมูล 'ยี่ห้อ', 'รุ่นยาง', หรือ 'เบอร์ยาง' ไม่สามารถเว้นว่างได้")

                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    price_per_item = float(row['ราคาต่อเส้น']) if pd.notna(row['ราคาต่อเส้น']) else 0.0
                    
                    cost_sc_raw = row.get('ทุน SC')
                    cost_dunlop_raw = row.get('ทุน Dunlop')
                    cost_online_raw = row.get('ทุน Online')
                    wholesale_price1_raw = row.get('ราคาขายส่ง 1')
                    wholesale_price2_raw = row.get('ราคาขายส่ง 2')
                    year_of_manufacture_raw = row.get('ปีผลิต')

                    cost_sc = float(cost_sc_raw) if pd.notna(cost_sc_raw) else None
                    cost_dunlop = float(cost_dunlop_raw) if pd.notna(cost_dunlop_raw) else None
                    cost_online = float(cost_online_raw) if pd.notna(cost_online_raw) else None
                    wholesale_price1 = float(wholesale_price1_raw) if pd.notna(wholesale_price1_raw) else None
                    wholesale_price2 = float(wholesale_price2_raw) if pd.notna(wholesale_price2_raw) else None
                    
                    promotion_id = int(row.get('ID โปรโมชัน')) if pd.notna(row.get('ID โปรโมชัน')) else None
                    
                    year_of_manufacture = str(year_of_manufacture_raw).strip() if pd.notna(year_of_manufacture_raw) else None
                    if year_of_manufacture == 'nan': # กรณีที่ excel อ่าน nan เป็น string 'nan'
                        year_of_manufacture = None
                    
                    cursor = conn.cursor()
                    if "psycopg2" in str(type(conn)):
                        cursor.execute("SELECT id, quantity FROM tires WHERE brand = %s AND model = %s AND size = %s", (brand, model, size))
                    else:
                        cursor.execute("SELECT id, quantity FROM tires WHERE brand = ? AND model = ? AND size = ?", (brand, model, size))
                    existing_tire = cursor.fetchone()

                    if existing_tire:
                        tire_id = existing_tire['id']
                        database.update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                    promotion_id, year_of_manufacture)
                        updated_count += 1
                        
                        old_quantity = existing_tire['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_tire_movement(conn, tire_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                        
                    else:
                        new_tire_id = database.add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                               promotion_id, year_of_manufacture)
                        database.add_tire_movement(conn, new_tire_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None, user_id=current_user.id)
                        imported_count += 1
                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")
            
            conn.commit()
            
            message = f'นำเข้าข้อมูลยางสำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:3])}{"..." if len(error_rows) > 3 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')
            
            return redirect(url_for('export_import', tab='tires_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการนำเข้าไฟล์ Excel ของยาง: {e}', 'danger')
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('export_import', tab='tires_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))

@app.route('/export_wheels_action')
@login_required
def export_wheels_action():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการส่งออกข้อมูลแม็ก', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))
    conn = get_db()
    wheels = database.get_all_wheels(conn)
    
    if not wheels:
        flash('ไม่มีข้อมูลแม็กให้ส่งออก', 'warning')
        return redirect(url_for('export_import', tab='wheels_excel'))

    data = []
    for wheel in wheels:
        data.append({
            'ID': wheel['id'],
            'ยี่ห้อ': wheel['brand'],
            'ลาย': wheel['model'],
            'ขอบ': wheel['diameter'],
            'รู': wheel['pcd'],
            'กว้าง': wheel['width'],
            'ET': wheel['et'],
            'สี': wheel['color'],
            'สต็อก': wheel['quantity'],
            'ทุน': wheel['cost'],
            'ทุน Online': wheel['cost_online'],
            'ราคาขายส่ง 1': wheel['wholesale_price1'],
            'ราคาขายส่ง 2': wheel['wholesale_price2'],
            'ราคาขายปลีก': wheel['retail_price'],
            'ไฟล์รูปภาพ': wheel['image_filename']
        })

    df = pd.DataFrame(data)

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Wheels Stock')
    writer.close()
    output.seek(0)

    return send_file(output, download_name='wheel_stock.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/import_wheels_action', methods=('POST',))
@login_required
def import_wheels_action():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการนำเข้าข้อมูลแม็ก', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))
    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))
    
    if file and allowed_excel_file(file.filename):
        try:
            df = pd.read_excel(file)
            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            expected_wheel_cols = [
                'ยี่ห้อ', 'ลาย', 'ขอบ', 'รู', 'กว้าง', 'ET', 'สี', 'สต็อก',
                'ทุน', 'ทุน Online', 'ราคาขายส่ง 1', 'ราคาขายส่ง 2', 'ราคาขายปลีก', 'ไฟล์รูปภาพ'
            ]
            if not all(col in df.columns for col in expected_wheel_cols):
                missing_cols = [col for col in expected_wheel_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                return redirect(url_for('export_import', tab='wheels_excel'))


            for index, row in df.iterrows():
                try:
                    brand = str(row.get('ยี่ห้อ', '')).strip().lower()
                    model = str(row.get('ลาย', '')).strip().lower()
                    pcd = str(row.get('รู', '')).strip()

                    if not brand or not model or not pcd:
                            raise ValueError("ข้อมูล 'ยี่ห้อ', 'ลาย', หรือ 'รู' ไม่สามารถเว้นว่างได้")

                    diameter = float(row['ขอบ']) if pd.notna(row['ขอบ']) else 0.0
                    width = float(row['กว้าง']) if pd.notna(row['กว้าง']) else 0.0
                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    cost = float(row['ทุน']) if pd.notna(row['ทุน']) else None
                    retail_price = float(row['ราคาขายปลีก']) if pd.notna(row['ราคาขายปลีก']) else 0.0
                    
                    et_raw = row.get('ET')
                    color_raw = row.get('สี')
                    image_url_raw = row.get('ไฟล์รูปภาพ')
                    cost_online_raw = row.get('ทุน Online')
                    wholesale_price1_raw = row.get('ราคาขายส่ง 1')
                    wholesale_price2_raw = row.get('ราคาขายส่ง 2')

                    et = int(et_raw) if pd.notna(et_raw) else None # ใช้ et_raw
                    color = str(color_raw).strip() if pd.notna(color_raw) else None # ใช้ color_raw
                    image_url = str(image_url_raw).strip() if pd.notna(image_url_raw) else None # ใช้ image_url_raw
                    cost_online = float(cost_online_raw) if pd.notna(cost_online_raw) else None # ใช้ cost_online_raw
                    wholesale_price1 = float(wholesale_price1_raw) if pd.notna(wholesale_price1_raw) else None # ใช้ wholesale_price1_raw
                    wholesale_price2 = float(wholesale_price2_raw) if pd.notna(wholesale_price2_raw) else None # ใช้ wholesale_price2_raw
                    
                    cursor = conn.cursor()
                    if "psycopg2" in str(type(conn)):
                        cursor.execute("SELECT id, quantity FROM wheels WHERE brand = %s AND model = %s AND diameter = %s AND pcd = %s AND width = %s AND (et IS %s OR et = %s) AND (color IS %s OR color = %s)", 
                                                 (brand, model, diameter, pcd, width, et, et, color, color))
                    else:
                        cursor.execute("SELECT id, quantity FROM wheels WHERE brand = ? AND model = ? AND diameter = ? AND pcd = ? AND width = ? AND (et IS ? OR et = ?) AND (color IS ? OR color = ?)", 
                                                 (brand, model, diameter, pcd, width, et, et, color, color))
                    existing_wheel = cursor.fetchone()

                    if existing_wheel:
                        wheel_id = existing_wheel['id']
                        database.update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        updated_count += 1
                        
                        old_quantity = existing_wheel['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_wheel_movement(conn, wheel_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                    else:
                        new_wheel_id = database.add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        database.add_wheel_movement(conn, new_wheel_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None, user_id=current_user.id)
                        imported_count += 1
                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")
            
            conn.commit()
            
            message = f'นำเข้าข้อมูลแม็กสำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:3])}{"..." if len(error_rows) > 3 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')
            
            return redirect(url_for('export_import', tab='wheels_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการนำเข้าไฟล์ Excel ของแม็ก: {e}', 'danger')
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('export_import', tab='wheels_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))


# --- User management routes ---
@app.route('/manage_users')
@login_required
def manage_users():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้าจัดการผู้ใช้', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role FROM users")
    users = cursor.fetchall()
    return render_template('manage_users.html', users=users)

@app.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_new_user():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการเพิ่มผู้ใช้', 'danger')
        return redirect(url_for('manage_users'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form.get('role', 'viewer')

        if not username or not password or not confirm_password:
            flash('กรุณากรอกข้อมูลให้ครบถ้วน', 'danger')
        elif password != confirm_password:
            flash('รหัสผ่านไม่ตรงกัน', 'danger')
        else:
            conn = get_db()
            user_id = database.add_user(conn, username, password, role)
            if user_id:
                flash(f'เพิ่มผู้ใช้ "{username}" สำเร็จ!', 'success')
                return redirect(url_for('manage_users'))
            else:
                flash(f'ชื่อผู้ใช้ "{username}" มีอยู่ในระบบแล้ว', 'danger')
    return render_template('add_user.html')

@app.route('/edit_user_role/<int:user_id>', methods=['POST'])
@login_required
def edit_user_role(user_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขบทบาทผู้ใช้', 'danger')
        return redirect(url_for('manage_users'))
    
    if str(user_id) == current_user.get_id():
        flash('ไม่สามารถแก้ไขบทบาทของผู้ใช้ที่กำลังเข้าสู่ระบบอยู่ได้', 'danger')
        return redirect(url_for('manage_users'))

    new_role = request.form.get('role')
    if new_role not in ['admin', 'editor', 'viewer']:
        flash('บทบาทไม่ถูกต้อง', 'danger')
        return redirect(url_for('manage_users'))

    conn = get_db()
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
    else:
        cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()
    flash(f'แก้ไขบทบาทผู้ใช้ ID {user_id} เป็น "{new_role}" สำเร็จ!', 'success')
    return redirect(url_for('manage_users'))


@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการลบผู้ใช้', 'danger')
        return redirect(url_for('manage_users'))

    conn = get_db()
    if str(user_id) == current_user.get_id():
        flash('ไม่สามารถลบผู้ใช้ที่กำลังเข้าสู่ระบบอยู่ได้', 'danger')
    else:
        cursor = conn.cursor()
        if "psycopg2" in str(type(conn)):
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        else:
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash('ลบผู้ใช้สำเร็จ!', 'success')
    return redirect(url_for('manage_users'))

# --- Admin Dashboard routes ---
@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึง Admin Dashboard', 'danger')
        return redirect(url_for('index'))
    return render_template('admin_dashboard.html')

@app.route('/admin_deleted_items')
@login_required
def admin_deleted_items():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้ารายการสินค้าที่ถูกลบ', 'danger')
        return redirect(url_for('index'))
    
    conn = get_db()
    deleted_tires = database.get_deleted_tires(conn)
    deleted_wheels = database.get_deleted_wheels(conn)
    
    active_tab = request.args.get('tab', 'deleted_tires')

    return render_template('admin_deleted_items.html', 
                           deleted_tires=deleted_tires, 
                           deleted_wheels=deleted_wheels,
                           active_tab=active_tab)

@app.route('/restore_tire/<int:tire_id>', methods=['POST'])
@login_required
def restore_tire_action(tire_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการกู้คืนยาง', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    try:
        database.restore_tire(conn, tire_id)
        flash(f'กู้คืนยาง ID {tire_id} สำเร็จ!', 'success')
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการกู้คืนยาง: {e}', 'danger')
    return redirect(url_for('admin_deleted_items', tab='deleted_tires'))

@app.route('/restore_wheel/<int:wheel_id>', methods=['POST'])
@login_required
def restore_wheel_action(wheel_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการกู้คืนแม็ก', 'danger')
        return redirect(url_for('index'))
    conn = get_db()
    try:
        database.restore_wheel(conn, wheel_id)
        flash(f'กู้คืนแม็ก ID {wheel_id} สำเร็จ!', 'success')
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการกู้คืนแม็ก: {e}', 'danger')
    return redirect(url_for('admin_deleted_items', tab='deleted_wheels'))


# --- Main entry point ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
