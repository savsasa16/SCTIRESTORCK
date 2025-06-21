# app.py
import sqlite3
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import re
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_file, current_app, jsonify
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

            # --- แก้ไขตรงนี้: Barcode ID เป็นทางเลือก (optional) ---
            scanned_barcode_for_add = request.form.get('barcode_id_for_add', '').strip()
            # ----------------------------------------------------

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
            
            # --- เพิ่ม/ปรับการตรวจสอบ Barcode ID ที่กรอกมา (ถ้ามี) ---
            if scanned_barcode_for_add: # ตรวจสอบเฉพาะถ้ามีการกรอก Barcode ID
                existing_barcode_tire_id = database.get_tire_id_by_barcode(conn, scanned_barcode_for_add)
                existing_barcode_wheel_id = database.get_wheel_id_by_barcode(conn, scanned_barcode_for_add)
                if existing_barcode_tire_id or existing_barcode_wheel_id:
                    flash(f"Barcode ID '{scanned_barcode_for_add}' มีอยู่ในระบบแล้ว. ไม่สามารถใช้ซ้ำได้.", 'danger')
                    active_tab = 'tire'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            # --------------------------------------------------------

            try:
                quantity = int(quantity)
                price_per_item = float(price_per_item)

                cost_sc = float(cost_sc) if cost_sc and cost_sc.strip() else None
                cost_dunlop = float(cost_dunlop) if cost_dunlop and cost_dunlop.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None
                
                year_of_manufacture = year_of_manufacture.strip() if year_of_manufacture and year_of_manufacture.strip() else None

                cursor = conn.cursor()
                if "psycopg2" in str(type(conn)):
                    cursor.execute("SELECT id FROM tires WHERE brand = %s AND model = %s AND size = %s", (brand, model, size))
                else:
                    cursor.execute("SELECT id FROM tires WHERE brand = ? AND model = ? AND size = ?", (brand, model, size))
                
                existing_tire = cursor.fetchone()

                if existing_tire:
                    flash(f'ยาง {brand.title()} รุ่น {model.title()} เบอร์ {size} มีอยู่ในระบบแล้ว หากต้องการแก้ไข กรุณาไปที่หน้าสต็อก', 'warning')
                else:
                    new_tire_id = database.add_tire(conn, brand, model, size, quantity,
                                                    cost_sc, cost_dunlop, cost_online,
                                                    wholesale_price1, wholesale_price2,
                                                    price_per_item, promotion_id_db,
                                                    year_of_manufacture,
                                                    user_id=current_user_id)
                    # --- เพิ่มตรงนี้: บันทึก Barcode ID สำหรับยาง (เฉพาะถ้ามีการกรอก) ---
                    if scanned_barcode_for_add:
                        database.add_tire_barcode(conn, new_tire_id, scanned_barcode_for_add, is_primary=True)
                    # -------------------------------------------------------------------                    
                    conn.commit()
                    flash(f'เพิ่มยาง {brand.title()} รุ่น {model.title()} เบอร์ {size} จำนวน {quantity} เส้น สำเร็จ!', 'success')
                return redirect(url_for('add_item', tab='tire'))

            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: ข้อมูลซ้ำซ้อนในระบบ หรือ Barcode ID นี้มีอยู่แล้ว. รายละเอียด: {e}', 'warning')
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

            scanned_barcode_for_add = request.form.get('barcode_id_for_add', '').strip()

            cost = request.form.get('cost')
            retail_price = request.form['retail_price']
            et = request.form.get('et')
            color = request.form.get('color', '').strip()
            cost_online = request.form.get('cost_online')
            wholesale_price1 = request.form.get('wholesale_price1')
            wholesale_price2 = request.form.get('wholesale_price2')
            
            image_file = request.files.get('image_file') 
            image_url = None # กำหนดค่าเริ่มต้น
            
            if image_file and image_file.filename != '':
                if allowed_image_file(image_file.filename):
                    try: # <--- เริ่มต้น try block สำหรับการอัปโหลด Cloudinary
                        upload_result = cloudinary.uploader.upload(image_file)
                        image_url = upload_result['secure_url']
                    except Exception as e: # <--- except block ที่จับ error จาก Cloudinary upload
                        flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพไปยังเซิฟเวอร์: {e}', 'danger')
                        active_tab = 'wheel'
                        return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                else: # <--- else block ของ if allowed_image_file
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    active_tab = 'wheel'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            # ไม่มี else: ตรงนี้แล้ว เพราะเป็นโครงสร้าง try-except-else ที่ใช้กับ try/except เท่านั้น

            # ... (โค้ดต่อจากการจัดการรูปภาพ: validation ของ form fields, ตรวจสอบ barcode) ...
            if not brand or not model or not pcd or not diameter or not width or not quantity or not retail_price:
                flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            
            # ... (ต่อด้วยการตรวจสอบ Barcode ID และ try/except หลักของ add_wheel) ...
            try: # <--- นี่คือ try block หลักสำหรับ logic การเพิ่มแม็กทั้งหมด
                diameter = float(diameter)
                width = float(width)
                quantity = int(quantity)
                retail_price = float(retail_price)

                cost = float(cost) if cost and cost.strip() else None
                et = int(et) if et and et.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None
                
                cursor = conn.cursor()
                if "psycopg2" in str(type(conn)):
                    cursor.execute("SELECT id FROM wheels WHERE brand = %s AND model = %s AND diameter = %s AND width = %s AND pcd = %s AND et = %s", 
                                   (brand, model, diameter, width, pcd, et))
                else:
                    cursor.execute("SELECT id FROM wheels WHERE brand = ? AND model = ? AND diameter = ? AND width = ? AND pcd = ? AND et = ?", 
                                   (brand, model, diameter, width, pcd, et))
                
                existing_wheel = cursor.fetchone()

                if existing_wheel:
                    flash(f'แม็ก {brand.title()} ลาย {model.title()} ขนาด {diameter}x{width} มีอยู่ในระบบแล้ว', 'warning')
                else:
                    new_wheel_id = database.add_wheel(conn, brand, model, diameter, pcd, width, et, color, 
                                                    quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                    if scanned_barcode_for_add:
                        database.add_wheel_barcode(conn, new_wheel_id, scanned_barcode_for_add, is_primary=True)
                    database.add_wheel_movement(conn, new_wheel_id, 'IN', quantity, quantity, "Initial Stock (Manual Add)", None, user_id=current_user.id)
                    conn.commit()
                    flash(f'เพิ่มแม็ก {brand.title()} ลาย {model.title()} จำนวน {quantity} วง สำเร็จ!', 'success')
                return redirect(url_for('index', tab='wheels'))
            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: ข้อมูลซ้ำซ้อนในระบบ หรือ Barcode ID นี้มีอยู่แล้ว. รายละเอียด: {e}', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มแม็ก: {e}', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            
            # --- เพิ่ม/ปรับการตรวจสอบ Barcode ID ที่กรอกมา (ถ้ามี) ---
            if scanned_barcode_for_add: # ตรวจสอบเฉพาะถ้ามีการกรอก Barcode ID
                existing_barcode_tire_id = database.get_tire_id_by_barcode(conn, scanned_barcode_for_add)
                existing_barcode_wheel_id = database.get_wheel_id_by_barcode(conn, scanned_barcode_for_add)
                if existing_barcode_tire_id or existing_barcode_wheel_id:
                    flash(f"Barcode ID '{scanned_barcode_for_add}' มีอยู่ในระบบแล้ว. ไม่สามารถใช้ซ้ำได้.", 'danger')
                    active_tab = 'wheel'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            # --------------------------------------------------------

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
                            flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพไปยังเซิฟเวอร์: {e}', 'danger')
                            active_tab = 'wheel'
                            return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                    else:
                        flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                        active_tab = 'wheel'
                        return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                
                cursor = conn.cursor()
                if "psycopg2" in str(type(conn)):
                    cursor.execute("SELECT id FROM wheels WHERE brand = %s AND model = %s AND diameter = %s AND width = %s AND pcd = %s AND et = %s", 
                                   (brand, model, diameter, width, pcd, et))
                else:
                    cursor.execute("SELECT id FROM wheels WHERE brand = ? AND model = ? AND diameter = ? AND width = ? AND pcd = ? AND et = ?", 
                                   (brand, model, diameter, width, pcd, et))
                
                existing_wheel = cursor.fetchone()

                if existing_wheel:
                    flash(f'แม็ก {brand.title()} ลาย {model.title()} ขนาด {diameter}x{width} มีอยู่ในระบบแล้ว', 'warning')
                else:
                    new_wheel_id = database.add_wheel(conn, brand, model, diameter, pcd, width, et, color, 
                                                    quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                    # --- เพิ่มตรงนี้: บันทึก Barcode ID สำหรับแม็ก (เฉพาะถ้ามีการกรอก) ---
                    if scanned_barcode_for_add:
                        database.add_wheel_barcode(conn, new_wheel_id, scanned_barcode_for_add, is_primary=True)
                    # -----------------------------------------------------------------
                    database.add_wheel_movement(conn, new_wheel_id, 'IN', quantity, quantity, "Initial Stock (Manual Add)", None, user_id=current_user.id)
                    conn.commit()
                    flash(f'เพิ่มแม็ก {brand.title()} ลาย {model.title()} จำนวน {quantity} วง สำเร็จ!', 'success')
                return redirect(url_for('index', tab='wheels'))
            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: ข้อมูลซ้ำซ้อนในระบบ หรือ Barcode ID นี้มีอยู่แล้ว. รายละเอียด: {e}', 'warning')
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
    tire_barcodes = database.get_barcodes_for_tire(conn, tire_id)

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

    return render_template('edit_tire.html', tire=tire, current_year=current_year, all_promotions=all_promotions, tire_barcodes=tire_barcodes)
    
@app.route('/api/tire/<int:tire_id>/barcodes', methods=['POST', 'DELETE'])
@login_required
def api_manage_tire_barcodes(tire_id):
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการจัดการ Barcode ID"}), 403

    conn = get_db()
    data = request.get_json()
    barcode_string = data.get('barcode_string', '').strip()

    if not barcode_string:
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    try:
        if request.method == 'POST':
            # เพิ่ม Barcode ID ใหม่
            # ตรวจสอบว่า Barcode ID นี้มีอยู่ในระบบแล้วหรือไม่ (ไม่ว่าจะผูกกับยาง/แม็กอื่นหรือไม่)
            existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_string)
            existing_wheel_id_by_barcode = database.get_wheel_id_by_barcode(conn, barcode_string)

            if existing_tire_id_by_barcode:
                # ถ้า Barcode ผูกกับยางตัวอื่นที่ไม่ใช่ tire_id ปัจจุบัน
                if existing_tire_id_by_barcode != tire_id:
                    conn.rollback()
                    return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับยาง (ID: {existing_tire_id_by_barcode}) แล้ว"}), 409
                # ถ้า Barcode ผูกกับ tire_id ปัจจุบันอยู่แล้ว (พยายามเพิ่มซ้ำ)
                else:
                    # ถือว่าสำเร็จ ไม่ต้องทำอะไรอีก
                    return jsonify({"success": True, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับยางนี้อยู่แล้ว"}), 200
            
            # ถ้า Barcode ผูกกับแม็กตัวอื่น
            if existing_wheel_id_by_barcode:
                conn.rollback()
                return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับแม็ก (ID: {existing_wheel_id_by_barcode}) แล้ว"}), 409

            # ถ้า Barcode ยังไม่ถูกใช้เลย -> เพิ่มใหม่
            database.add_tire_barcode(conn, tire_id, barcode_string, is_primary=False) # is_primary = False สำหรับ Barcode ที่เพิ่มจากหน้า Edit
            conn.commit()
            return jsonify({"success": True, "message": "เพิ่ม Barcode สำเร็จ!"}), 200

        elif request.method == 'DELETE':
            # ลบ Barcode ID
            database.delete_tire_barcode(conn, barcode_string)
            conn.commit()
            return jsonify({"success": True, "message": "ลบ Barcode สำเร็จ!"}), 200
            
    except Exception as e:
        conn.rollback()
        # กรณี UNIQUE constraint failed อาจถูกจับใน add_tire_barcode ถ้าไม่มี ON CONFLICT
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
             return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' มีอยู่ในระบบแล้ว"}), 409
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการจัดการ Barcode ID: {str(e)}"}), 500

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
    
    wheel_barcodes = database.get_barcodes_for_wheel(conn, wheel_id)
    
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

    return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes)

@app.route('/api/wheel/<int:wheel_id>/barcodes', methods=['POST', 'DELETE'])
@login_required
def api_manage_wheel_barcodes(wheel_id):
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการจัดการ Barcode ID"}), 403

    conn = get_db()
    data = request.get_json()
    barcode_string = data.get('barcode_string', '').strip()

    if not barcode_string:
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    try:
        if request.method == 'POST':
            # เพิ่ม Barcode ID ใหม่
            existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_string)
            existing_wheel_id_by_barcode = database.get_wheel_id_by_barcode(conn, barcode_string)

            # ถ้า Barcode ผูกกับแม็กตัวอื่นที่ไม่ใช่ wheel_id ปัจจุบัน
            if existing_wheel_id_by_barcode: # This line always true if it finds any wheel
                if existing_wheel_id_by_barcode != wheel_id:
                    conn.rollback()
                    return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับแม็กอื่น (ID: {existing_wheel_id_by_barcode}) แล้ว"}), 409
                # ถ้า Barcode ผูกกับ wheel_id ปัจจุบันอยู่แล้ว (พยายามเพิ่มซ้ำ)
                else:
                    return jsonify({"success": True, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับแม็กนี้อยู่แล้ว"}), 200
            
            # ถ้า Barcode ผูกกับยางตัวอื่น
            if existing_tire_id_by_barcode:
                conn.rollback()
                return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับยาง (ID: {existing_tire_id_by_barcode}) แล้ว"}), 409
            
            # ถ้า Barcode ยังไม่ถูกใช้เลย -> เพิ่มใหม่
            database.add_wheel_barcode(conn, wheel_id, barcode_string, is_primary=False) # is_primary = False สำหรับ Barcode ที่เพิ่มจากหน้า Edit
            conn.commit()
            return jsonify({"success": True, "message": "เพิ่ม Barcode ID สำเร็จ!"}), 200

        elif request.method == 'DELETE':
            # ลบ Barcode ID
            database.delete_wheel_barcode(conn, barcode_string)
            conn.commit()
            return jsonify({"success": True, "message": "ลบ Barcode ID สำเร็จ!"}), 200
            
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการจัดการ Barcode ID: {str(e)}"}), 500

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
            report_datetime_obj = BKK_TZ.localize(datetime.strptime(report_date_str, '%Y-%m-%d')).replace(hour=0, minute=0, second=0, microsecond=0)
            display_date_str = report_datetime_obj.strftime('%d %b %Y')
        except ValueError:
            flash("รูปแบบวันที่ไม่ถูกต้อง กรุณาใช้YYYY-MM-DD", "danger")
            report_datetime_obj = get_bkk_time().replace(hour=0, minute=0, second=0, microsecond=0)
            display_date_str = report_datetime_obj.strftime('%d %b %Y')
    else:
        report_datetime_obj = get_bkk_time().replace(hour=0, minute=0, second=0, microsecond=0)
        display_date_str = report_datetime_obj.strftime('%d %b %Y')
    
    start_of_report_day_iso = report_datetime_obj.isoformat()    

    report_date = report_datetime_obj.date()
    sql_date_filter = report_date.strftime('%Y-%m-%d')
    sql_date_filter_end_of_day = report_datetime_obj.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

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
        cursor.execute(query_total_before_tires, (start_of_report_day_iso,))
    else:
        cursor.execute(query_total_before_tires.replace('%s', '?'), (start_of_report_day_iso,))
    
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
        cursor.execute(query_total_before_wheels, (start_of_report_day_iso,))
    else:
        cursor.execute(query_total_before_wheels.replace('%s', '?'), (start_of_report_day_iso,))
    
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

# --- NEW: Summary Stock Report Route ---
@app.route('/summary_stock_report')
@login_required
def summary_stock_report():
    conn = get_db()
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    today_bkk = get_bkk_time().date()

    if not start_date_str and not end_date_str:
        # Default to last 7 days if no dates are provided
        end_date_obj = today_bkk
        start_date_obj = today_bkk - timedelta(days=6)
        start_date_str = start_date_obj.strftime('%Y-%m-%d')
        end_date_str = end_date_obj.strftime('%Y-%m-%d')
    elif not start_date_str:
        # If only end_date is provided, default start_date to 7 days before end_date
        try:
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            start_date_obj = end_date_obj - timedelta(days=6)
            start_date_str = start_date_obj.strftime('%Y-%m-%d')
        except ValueError:
            flash("รูปแบบวันที่สิ้นสุดไม่ถูกต้อง กรุณาใช้ YYYY-MM-DD", "danger")
            end_date_obj = today_bkk
            start_date_obj = today_bkk - timedelta(days=6)
            start_date_str = start_date_obj.strftime('%Y-%m-%d')
            end_date_str = end_date_obj.strftime('%Y-%m-%d')
    elif not end_date_str:
        # If only start_date is provided, default end_date to today
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date_obj = today_bkk
            end_date_str = end_date_obj.strftime('%Y-%m-%d')
        except ValueError:
            flash("รูปแบบวันที่เริ่มต้นไม่ถูกต้อง กรุณาใช้ YYYY-MM-DD", "danger")
            end_date_obj = today_bkk
            start_date_obj = today_bkk - timedelta(days=6)
            start_date_str = start_date_obj.strftime('%Y-%m-%d')
            end_date_str = end_date_obj.strftime('%Y-%m-%d')
    else:
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("รูปแบบวันที่ไม่ถูกต้อง กรุณาใช้ YYYY-MM-DD", "danger")
            end_date_obj = today_bkk
            start_date_obj = today_bkk - timedelta(days=6)
            start_date_str = start_date_obj.strftime('%Y-%m-%d')
            end_date_str = end_date_obj.strftime('%Y-%m-%d')

    if start_date_obj > end_date_obj:
        flash("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด", "danger")
        start_date_obj = end_date_obj - timedelta(days=6)
        start_date_str = start_date_obj.strftime('%Y-%m-%d')


    display_range_str = f"{start_date_obj.strftime('%d %b %Y')} - {end_date_obj.strftime('%d %b %Y')}"

    # Convert to BKK localized datetime objects for queries
    start_datetime_obj = BKK_TZ.localize(datetime.combine(start_date_obj, datetime.min.time())).replace(hour=0, minute=0, second=0, microsecond=0)
    end_datetime_obj = BKK_TZ.localize(datetime.combine(end_date_obj, datetime.max.time())).replace(hour=23, minute=59, second=59, microsecond=999999)

    start_iso = start_datetime_obj.isoformat()
    end_iso = end_datetime_obj.isoformat()

    # --- Tire Data Processing for Summary Report ---
    cursor = conn.cursor()

    # Fetch all tire movements within the specified range (inclusive)
    tire_movements_in_range_query = f"""
        SELECT tm.tire_id, tm.type, tm.quantity_change, t.brand, t.model, t.size
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        WHERE tm.timestamp >= %s AND tm.timestamp <= %s
        ORDER BY t.brand, t.model, t.size, tm.timestamp ASC
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(tire_movements_in_range_query, (start_iso, end_iso))
        tire_movements_raw_range = cursor.fetchall()
    else:
        tire_movements_raw_range = conn.execute(tire_movements_in_range_query.replace('%s', '?'), (start_iso, end_iso)).fetchall()

    # Get all distinct tire IDs that had movements up to the END of the period
    # and also all existing (non-deleted) tires for accurate 'initial' and 'final' quantities
    all_involved_tire_ids = set()
    for move in tire_movements_raw_range:
        all_involved_tire_ids.add(move['tire_id'])
    
    existing_tires_query = f"""
        SELECT id FROM tires WHERE is_deleted = FALSE
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(existing_tires_query)
    else:
        cursor.execute(existing_tires_query.replace('FALSE', '0'))
    
    for row in cursor.fetchall():
        all_involved_tire_ids.add(row['id'])

    # Calculate initial quantities for each tire at the START of the report range
    tire_initial_quantities = defaultdict(int)
    for tire_id in all_involved_tire_ids:
        initial_qty_calc_query = f"""
            SELECT type, quantity_change
            FROM tire_movements
            WHERE tire_id = %s AND timestamp < %s
            ORDER BY timestamp ASC
        """
        if "psycopg2" in str(type(conn)):
            cursor.execute(initial_qty_calc_query, (tire_id, start_iso))
        else:
            cursor.execute(initial_qty_calc_query.replace('%s', '?'), (tire_id, start_iso,))
        
        calculated_initial_qty = 0
        for move in cursor.fetchall():
            if move['type'] == 'IN':
                calculated_initial_qty += move['quantity_change']
            elif move['type'] == 'OUT':
                calculated_initial_qty -= move['quantity_change']
        tire_initial_quantities[tire_id] = calculated_initial_qty

    # Process item-level movements for the range and aggregate for brand totals
    tires_by_brand_for_summary_report = defaultdict(list)
    tire_brand_totals_for_summary_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'final_quantity_sum': 0})
    
    item_range_summary = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'tire_id': None, 'brand': '', 'model': '', 'size': ''})

    for movement in tire_movements_raw_range:
        key = (movement['brand'], movement['model'], movement['size'])
        tire_id = movement['tire_id']

        item_range_summary[key]['tire_id'] = tire_id
        item_range_summary[key]['brand'] = movement['brand']
        item_range_summary[key]['model'] = movement['model']
        item_range_summary[key]['size'] = movement['size']

        if movement['type'] == 'IN':
            item_range_summary[key]['IN'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            item_range_summary[key]['OUT'] += movement['quantity_change']
    
    # Populate tires_by_brand_for_summary_report and initial calculations for brand totals
    sorted_item_range_summary_keys = sorted(item_range_summary.keys(), key=lambda x: (x[0], x[1], x[2]))

    for key in sorted_item_range_summary_keys:
        data = item_range_summary[key]
        tire_id = data['tire_id']
        brand = data['brand']

        initial_qty = tire_initial_quantities[tire_id]
        in_qty = data['IN']
        out_qty = data['OUT']
        final_qty = initial_qty + in_qty - out_qty

        item_data = {
            'brand': brand,
            'model': data['model'],
            'size': data['size'],
            'initial_quantity': initial_qty,
            'IN': in_qty,
            'OUT': out_qty,
            'final_quantity': final_qty
        }
        tires_by_brand_for_summary_report[brand].append(item_data)

        # Update brand totals (IN and OUT for the period)
        tire_brand_totals_for_summary_report[brand]['IN'] += in_qty
        tire_brand_totals_for_summary_report[brand]['OUT'] += out_qty
    
    # Add items that had initial stock but no movements in the range
    for tire_id, initial_qty in tire_initial_quantities.items():
        # Check if this tire_id was processed in item_range_summary (meaning it had movements)
        if initial_qty > 0 and not any(item_data['tire_id'] == tire_id for items_list in tires_by_brand_for_summary_report.values() for item_data in items_list):
            tire_info = database.get_tire(conn, tire_id)
            if tire_info and not tire_info['is_deleted']:
                brand = tire_info['brand']
                # Add to detailed report for display
                tires_by_brand_for_summary_report[brand].append({
                    'brand': brand,
                    'model': tire_info['model'],
                    'size': tire_info['size'],
                    'initial_quantity': initial_qty,
                    'IN': 0,
                    'OUT': 0,
                    'final_quantity': initial_qty # If no movement, final is same as initial
                })
                # For brands that only had initial stock and no movements, their IN/OUT are 0
                # But their final_quantity_sum still needs to reflect the initial quantity.
                # This will be handled in the final `final_quantity_sum` calculation loop below.

    # Calculate final_quantity_sum for each brand in tire_brand_totals_for_summary_report
    # This sums the final_quantity of all items belonging to that brand (which includes items with no movement during the period)
    for brand in tire_brand_totals_for_summary_report.keys():
        total_final_for_brand = 0
        if brand in tires_by_brand_for_summary_report: # Ensure the brand has items in the detailed report
            for item_data in tires_by_brand_for_summary_report[brand]:
                total_final_for_brand += item_data['final_quantity']
        tire_brand_totals_for_summary_report[brand]['final_quantity_sum'] = total_final_for_brand

    # Sort the brand totals for presentation
    sorted_tire_brand_totals = sorted(tire_brand_totals_for_summary_report.items(), key=lambda x: x[0])


    # --- Wheel Data Processing for Summary Report (similar logic) ---
    wheel_movements_in_range_query = f"""
        SELECT wm.wheel_id, wm.type, wm.quantity_change, w.brand, w.model, w.diameter, w.pcd, w.width
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        WHERE wm.timestamp >= %s AND wm.timestamp <= %s
        ORDER BY w.brand, w.model, w.diameter, wm.timestamp ASC
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(wheel_movements_in_range_query, (start_iso, end_iso))
        wheel_movements_raw_range = cursor.fetchall()
    else:
        wheel_movements_raw_range = conn.execute(wheel_movements_in_range_query.replace('%s', '?'), (start_iso, end_iso)).fetchall()

    all_involved_wheel_ids = set()
    for move in wheel_movements_raw_range:
        all_involved_wheel_ids.add(move['wheel_id'])

    existing_wheels_query = f"""
        SELECT id FROM wheels WHERE is_deleted = FALSE
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(existing_wheels_query)
    else:
        cursor.execute(existing_wheels_query.replace('FALSE', '0'))
    
    for row in cursor.fetchall():
        all_involved_wheel_ids.add(row['id'])

    wheel_initial_quantities = defaultdict(int)
    for wheel_id in all_involved_wheel_ids:
        initial_qty_calc_query = f"""
            SELECT type, quantity_change
            FROM wheel_movements
            WHERE wheel_id = %s AND timestamp < %s
            ORDER BY timestamp ASC
        """
        if "psycopg2" in str(type(conn)):
            cursor.execute(initial_qty_calc_query, (wheel_id, start_iso))
        else:
            cursor.execute(initial_qty_calc_query.replace('%s', '?'), (wheel_id, start_iso,))
        
        calculated_initial_qty = 0
        for move in cursor.fetchall():
            if move['type'] == 'IN':
                calculated_initial_qty += move['quantity_change']
            elif move['type'] == 'OUT':
                calculated_initial_qty -= move['quantity_change']
        wheel_initial_quantities[wheel_id] = calculated_initial_qty

    wheels_by_brand_for_summary_report = defaultdict(list)
    wheel_brand_totals_for_summary_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'final_quantity_sum': 0})

    item_range_summary_wheels = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'wheel_id': None, 'brand': '', 'model': '', 'diameter': None, 'pcd': '', 'width': None})

    for movement in wheel_movements_raw_range:
        key = (movement['brand'], movement['model'], movement['diameter'], movement['pcd'], movement['width'])
        wheel_id = movement['wheel_id']

        item_range_summary_wheels[key]['wheel_id'] = wheel_id
        item_range_summary_wheels[key]['brand'] = movement['brand']
        item_range_summary_wheels[key]['model'] = movement['model']
        item_range_summary_wheels[key]['diameter'] = movement['diameter']
        item_range_summary_wheels[key]['pcd'] = movement['pcd']
        item_range_summary_wheels[key]['width'] = movement['width']

        if movement['type'] == 'IN':
            item_range_summary_wheels[key]['IN'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            item_range_summary_wheels[key]['OUT'] += movement['quantity_change']

    sorted_item_range_summary_wheel_keys = sorted(item_range_summary_wheels.keys(), key=lambda x: (x[0], x[1], x[2], x[3], x[4]))

    for key in sorted_item_range_summary_wheel_keys:
        data = item_range_summary_wheels[key]
        wheel_id = data['wheel_id']
        brand = data['brand']

        initial_qty = wheel_initial_quantities[wheel_id]
        in_qty = data['IN']
        out_qty = data['OUT']
        final_qty = initial_qty + in_qty - out_qty

        item_data = {
            'brand': brand,
            'model': data['model'],
            'diameter': data['diameter'],
            'pcd': data['pcd'],
            'width': data['width'],
            'initial_quantity': initial_qty,
            'IN': in_qty,
            'OUT': out_qty,
            'final_quantity': final_qty
        }
        wheels_by_brand_for_summary_report[brand].append(item_data)

        wheel_brand_totals_for_summary_report[brand]['IN'] += in_qty
        wheel_brand_totals_for_summary_report[brand]['OUT'] += out_qty

    for wheel_id, initial_qty in wheel_initial_quantities.items():
        if initial_qty > 0 and not any(item_data['wheel_id'] == wheel_id for items_list in wheels_by_brand_for_summary_report.values() for item_data in items_list):
            wheel_info = database.get_wheel(conn, wheel_id)
            if wheel_info and not wheel_info['is_deleted']:
                brand = wheel_info['brand']
                wheels_by_brand_for_summary_report[brand].append({
                    'brand': brand,
                    'model': wheel_info['model'],
                    'diameter': wheel_info['diameter'],
                    'pcd': wheel_info['pcd'],
                    'width': wheel_info['width'],
                    'initial_quantity': initial_qty,
                    'IN': 0,
                    'OUT': 0,
                    'final_quantity': initial_qty
                })
    
    for brand in wheel_brand_totals_for_summary_report.keys():
        total_final_for_brand = 0
        if brand in wheels_by_brand_for_summary_report:
            for item_data in wheels_by_brand_for_summary_report[brand]:
                total_final_for_brand += item_data['final_quantity']
        wheel_brand_totals_for_summary_report[brand]['final_quantity_sum'] = total_final_for_brand

    sorted_wheel_brand_totals = sorted(wheel_brand_totals_for_summary_report.items(), key=lambda x: x[0])


    # Overall totals for the entire range (These are already calculated correctly in original daily_stock_report)
    overall_tire_initial_query = f"""
        SELECT SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END)
        FROM tire_movements
        WHERE timestamp < %s
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(overall_tire_initial_query, (start_iso,))
    else:
        cursor.execute(overall_tire_initial_query.replace('%s', '?'), (start_iso,))
    overall_tire_initial = cursor.fetchone()[0] or 0

    overall_wheel_initial_query = f"""
        SELECT SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END)
        FROM wheel_movements
        WHERE timestamp < %s
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(overall_wheel_initial_query, (start_iso,))
    else:
        cursor.execute(overall_wheel_initial_query.replace('%s', '?'), (start_iso,))
    overall_wheel_initial = cursor.fetchone()[0] or 0

    overall_tire_in_query = f"""
        SELECT SUM(quantity_change) FROM tire_movements WHERE type = 'IN' AND timestamp >= %s AND timestamp <= %s
    """
    overall_tire_out_query = f"""
        SELECT SUM(quantity_change) FROM tire_movements WHERE type = 'OUT' AND timestamp >= %s AND timestamp <= %s
    """
    overall_wheel_in_query = f"""
        SELECT SUM(quantity_change) FROM wheel_movements WHERE type = 'IN' AND timestamp >= %s AND timestamp <= %s
    """
    overall_wheel_out_query = f"""
        SELECT SUM(quantity_change) FROM wheel_movements WHERE type = 'OUT' AND timestamp >= %s AND timestamp <= %s
    """

    if "psycopg2" in str(type(conn)):
        cursor.execute(overall_tire_in_query, (start_iso, end_iso))
        overall_tire_in = cursor.fetchone()[0] or 0
        cursor.execute(overall_tire_out_query, (start_iso, end_iso))
        overall_tire_out = cursor.fetchone()[0] or 0
        cursor.execute(overall_wheel_in_query, (start_iso, end_iso))
        overall_wheel_in = cursor.fetchone()[0] or 0
        cursor.execute(overall_wheel_out_query, (start_iso, end_iso))
        overall_wheel_out = cursor.fetchone()[0] or 0
    else:
        overall_tire_in = conn.execute(overall_tire_in_query.replace('%s', '?'), (start_iso, end_iso)).fetchone()[0] or 0
        overall_tire_out = conn.execute(overall_tire_out_query.replace('%s', '?'), (start_iso, end_iso)).fetchone()[0] or 0
        overall_wheel_in = conn.execute(overall_wheel_in_query.replace('%s', '?'), (start_iso, end_iso)).fetchone()[0] or 0
        overall_wheel_out = conn.execute(overall_wheel_out_query.replace('%s', '?'), (start_iso, end_iso)).fetchone()[0] or 0
    
    # Overall final quantities based on current actual stock (from tires/wheels tables)
    overall_tire_final_query = f"""
        SELECT SUM(quantity) FROM tires WHERE is_deleted = FALSE
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(overall_tire_final_query)
    else:
        cursor.execute(overall_tire_final_query.replace('FALSE', '0'))
    overall_tire_final = cursor.fetchone()[0] or 0

    overall_wheel_final_query = f"""
        SELECT SUM(quantity) FROM wheels WHERE is_deleted = FALSE
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(overall_wheel_final_query)
    else:
        cursor.execute(overall_wheel_final_query.replace('FALSE', '0'))
    overall_wheel_final = cursor.fetchone()[0] or 0


    return render_template('summary_stock_report.html',
                           start_date_param=start_date_str,
                           end_date_param=end_date_str,
                           display_range_str=display_range_str,
                           
                           tires_by_brand_for_summary_report=tires_by_brand_for_summary_report,
                           wheels_by_brand_for_summary_report=wheels_by_brand_for_summary_report,
                           
                           tire_brand_totals_for_summary_report=sorted_tire_brand_totals,
                           wheel_brand_totals_for_summary_report=sorted_wheel_brand_totals,

                           overall_tire_initial=overall_tire_initial,
                           overall_tire_in=overall_tire_in,
                           overall_tire_out=overall_tire_out,
                           overall_tire_final=overall_tire_final,
                           overall_wheel_initial=overall_wheel_initial,
                           overall_wheel_in=overall_wheel_in,
                           overall_wheel_out=overall_wheel_out,
                           overall_wheel_final=overall_wheel_final
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

            # --- ตรวจสอบคอลัมน์ Barcode ID ใน Excel ---
            expected_tire_cols = [
                'ยี่ห้อ', 'รุ่นยาง', 'เบอร์ยาง', 'สต็อก', 'ทุน SC', 'ทุน Dunlop', 'ทุน Online',
                'ราคาขายส่ง 1', 'ราคาขายส่ง 2', 'ราคาต่อเส้น', 'ID โปรโมชัน', 'ปีผลิต',
                'Barcode ID' # <-- คอลัมน์นี้ยังจำเป็นสำหรับการ Import
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

                    # --- รับ Barcode ID จาก Excel (ยังคงเป็น Required) ---
                    barcode_id_from_excel = str(row.get('Barcode ID', '')).strip()
                    if not barcode_id_from_excel:
                        raise ValueError("คอลัมน์ 'Barcode ID' ไม่สามารถเว้นว่างได้สำหรับยางในการนำเข้า Excel")
                    # -----------------------------------------------------
                    
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
                    
                    year_of_manufacture = None 
                    if pd.notna(year_of_manufacture_raw):
                        try:
                            year_of_manufacture = int(year_of_manufacture_raw)
                        except ValueError:
                            year_of_manufacture = str(year_of_manufacture_raw).strip()
                            if year_of_manufacture == 'nan':
                                year_of_manufacture = None

                    promotion_id = int(row.get('ID โปรโมชัน')) if pd.notna(row.get('ID โปรโมชัน')) else None
                    
                    cursor = conn.cursor()
                    
                    # ปรับการค้นหา Tire ที่มีอยู่แล้ว ให้ใช้ Barcode ID ก่อน
                    tire_id_from_barcode = database.get_tire_id_by_barcode(conn, barcode_id_from_excel)
                    existing_tire = None
                    if tire_id_from_barcode:
                        if "psycopg2" in str(type(conn)):
                            cursor.execute("SELECT id, quantity FROM tires WHERE id = %s", (tire_id_from_barcode,))
                        else:
                            cursor.execute("SELECT id, quantity FROM tires WHERE id = ?", (tire_id_from_barcode,))
                        existing_tire = cursor.fetchone()
                    
                    # ถ้าไม่เจอด้วย Barcode ID ให้ลองค้นหาด้วย Brand, Model, Size (เป็น Fallback)
                    if not existing_tire:
                         if "psycopg2" in str(type(conn)):
                            cursor.execute("SELECT id, quantity FROM tires WHERE brand = %s AND model = %s AND size = %s", (brand, model, size))
                         else:
                            cursor.execute("SELECT id, quantity FROM tires WHERE brand = ? AND model = ? AND size = ?", (brand, model, size))
                         existing_tire = cursor.fetchone()

                    if existing_tire:
                        tire_id = existing_tire['id']
                        database.update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                    promotion_id, year_of_manufacture)
                        # อัปเดต Barcode ID ด้วย ถ้ามีการอัปเดตหลัก (หรือยืนยันว่า Barcode ID ยังอยู่)
                        database.add_tire_barcode(conn, tire_id, barcode_id_from_excel, is_primary=True) 
                        updated_count += 1
                        
                        old_quantity = existing_tire['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_tire_movement(conn, tire_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                        
                    else:
                        new_tire_id = database.add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                                promotion_id, year_of_manufacture)
                        # บันทึก Barcode ID สำหรับยางที่เพิ่มใหม่
                        database.add_tire_barcode(conn, new_tire_id, barcode_id_from_excel, is_primary=True)
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

            # --- ตรวจสอบคอลัมน์ Barcode ID ใน Excel ---
            expected_wheel_cols = [
                'ยี่ห้อ', 'ลาย', 'ขอบ', 'รู', 'กว้าง', 'ET', 'สี', 'สต็อก',
                'ทุน', 'ทุน Online', 'ราคาขายส่ง 1', 'ราคาขายส่ง 2', 'ราคาขายปลีก', 'ไฟล์รูปภาพ',
                'Barcode ID' # <-- คอลัมน์นี้ยังจำเป็นสำหรับการ Import
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

                    # --- รับ Barcode ID จาก Excel (ยังคงเป็น Required) ---
                    barcode_id_from_excel = str(row.get('Barcode ID', '')).strip()
                    if not barcode_id_from_excel:
                        raise ValueError("คอลัมน์ 'Barcode ID' ไม่สามารถเว้นว่างได้สำหรับแม็กในการนำเข้า Excel")
                    # ---------------------------------------------------

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

                    et = int(et_raw) if pd.notna(et_raw) else None
                    color = str(color_raw).strip() if pd.notna(color_raw) else None
                    image_url = str(image_url_raw).strip() if pd.notna(image_url_raw) else None
                    cost_online = float(cost_online_raw) if pd.notna(cost_online_raw) else None
                    wholesale_price1 = float(wholesale_price1_raw) if pd.notna(wholesale_price1_raw) else None
                    wholesale_price2 = float(wholesale_price2_raw) if pd.notna(wholesale_price2_raw) else None
                    
                    cursor = conn.cursor()

                    # ปรับการค้นหา Wheel ที่มีอยู่แล้ว ให้ใช้ Barcode ID ก่อน
                    wheel_id_from_barcode = database.get_wheel_id_by_barcode(conn, barcode_id_from_excel)
                    existing_wheel = None
                    if wheel_id_from_barcode:
                        if "psycopg2" in str(type(conn)):
                            cursor.execute("SELECT id, quantity FROM wheels WHERE id = %s", (wheel_id_from_barcode,))
                        else:
                            cursor.execute("SELECT id, quantity FROM wheels WHERE id = ?", (wheel_id_from_barcode,))
                        existing_wheel = cursor.fetchone()

                    # ถ้าไม่เจอด้วย Barcode ID ให้ลองค้นหาด้วย Brand, Model, Diameter, PCD, Width (เป็น Fallback)
                    if not existing_wheel:
                        if "psycopg2" in str(type(conn)):
                            cursor.execute("SELECT id, quantity FROM wheels WHERE brand = %s AND model = %s AND diameter = %s AND pcd = %s AND width = %s", 
                                        (brand, model, diameter, pcd, width))
                        else:
                            cursor.execute("SELECT id, quantity FROM wheels WHERE brand = ? AND model = ? AND diameter = ? AND width = ? AND pcd = ? AND et = ?", 
                                        (brand, model, diameter, pcd, width))
                        existing_wheel = cursor.fetchone()
                    
                    if existing_wheel:
                        wheel_id = existing_wheel['id']
                        database.update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        # อัปเดต Barcode ID ด้วย ถ้ามีการอัปเดตหลัก (หรือยืนยันว่า Barcode ID ยังอยู่)
                        database.add_wheel_barcode(conn, wheel_id, barcode_id_from_excel, is_primary=True)
                        updated_count += 1
                        
                        old_quantity = existing_wheel['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_wheel_movement(conn, wheel_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                        
                    else:
                        new_wheel_id = database.add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        # บันทึก Barcode ID สำหรับแม็กที่เพิ่มใหม่
                        database.add_wheel_barcode(conn, new_wheel_id, barcode_id_from_excel, is_primary=True)
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

@app.route('/barcode_scanner')
@login_required
def barcode_scanner_page():
    """Renders the barcode scanning page."""
    return render_template('barcode_scanner.html')
    
@app.route('/api/scan_item_lookup', methods=['GET'])
@login_required
def api_scan_item_lookup():
    scanned_barcode_string = request.args.get('barcode_id')
    if not scanned_barcode_string:
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    conn = get_db()

    # --- ขั้นตอนที่ 1: ค้นหาในตาราง tire_barcodes ---
    tire_id = database.get_tire_id_by_barcode(conn, scanned_barcode_string)
    if tire_id:
        tire = database.get_tire(conn, tire_id) # ดึงข้อมูลยางหลัก
        if tire:
            # แปลง sqlite3.Row/DictRow เป็น dict เพื่อให้ง่ายต่อการส่ง JSON
            if not isinstance(tire, dict):
                tire = dict(tire)
            tire['type'] = 'tire'
            tire['current_quantity'] = tire['quantity'] # ใช้ current_quantity ใน Frontend
            return jsonify({"success": True, "item": tire})

    # --- ขั้นตอนที่ 2: ค้นหาในตาราง wheel_barcodes ---
    wheel_id = database.get_wheel_id_by_barcode(conn, scanned_barcode_string)
    if wheel_id:
        wheel = database.get_wheel(conn, wheel_id) # ดึงข้อมูลแม็กหลัก
        if wheel:
            if not isinstance(wheel, dict):
                wheel = dict(wheel)
            wheel['type'] = 'wheel'
            wheel['current_quantity'] = wheel['quantity'] # ใช้ current_quantity ใน Frontend
            return jsonify({"success": True, "item": wheel})

    # --- ถ้าไม่พบเลย: ส่งคืนข้อความว่าไม่พบ และแนะนำให้เชื่อมโยง ---
    return jsonify({
        "success": False,
        "message": f"ไม่พบสินค้าสำหรับบาร์โค้ด: '{scanned_barcode_string}'. คุณต้องการเชื่อมโยงบาร์โค้ดนี้กับสินค้าที่มีอยู่หรือไม่?",
        "action_required": "link_new_barcode", # บอก Frontend ให้เปิด Modal เชื่อมโยง
        "scanned_barcode": scanned_barcode_string # ส่ง Barcode ที่สแกนกลับไปด้วย
    }), 404
    
@app.route('/api/process_stock_transaction', methods=['POST'])
@login_required
def api_process_stock_transaction():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "ไม่มีข้อมูลส่งมา"}), 400

    transaction_type = data.get('type') # 'IN' or 'OUT'
    items_to_process = data.get('items', [])
    notes = data.get('notes', '') # รับ notes จาก Frontend
    user_id = current_user.id if current_user.is_authenticated else None

    if transaction_type not in ['IN', 'OUT']:
        return jsonify({"success": False, "message": "ประเภทการทำรายการไม่ถูกต้อง (ต้องเป็น IN หรือ OUT)"}), 400
    if not items_to_process:
        return jsonify({"success": False, "message": "ไม่มีรายการสินค้าให้ทำรายการ"}), 400

    conn = get_db()
    # ใช้ try...except บล็อกเพื่อให้แน่ใจว่ามีการ rollback transaction ถ้าเกิดข้อผิดพลาด
    try:
        # เริ่มต้น transaction (สำหรับ psycopg2 จะจัดการโดยอัตโนมัติเมื่อใช้ cursor, สำหรับ SQLite อาจต้องใช้ conn.begin() หากต้องการ Transaction แยกย่อย)
        # conn.autocommit = False # ถ้าใช้ psycopg2 และต้องการควบคุม transaction เอง
        
        # สำหรับ SQLite ที่ไม่มี explicit begin() ต้องมั่นใจว่าการ execute แต่ละครั้งอยู่ใน scope ที่ต้องการ
        # ในที่นี้ เราจะให้ Flask จัดการ conn.commit() หรือ conn.rollback() ท้ายสุด
        
        for item_data in items_to_process:
            item_id = item_data.get('id')
            item_type = item_data.get('item_type')
            quantity_change = item_data.get('quantity') # ใช้ quantity_change เพื่อสื่อถึงจำนวนที่เปลี่ยน

            # ตรวจสอบข้อมูลพื้นฐาน
            if not item_id or not item_type or not quantity_change or not isinstance(quantity_change, int) or quantity_change <= 0:
                # ถ้าข้อมูลไม่สมบูรณ์ ให้ rollback ทันที
                conn.rollback() 
                return jsonify({"success": False, "message": f"ข้อมูลสินค้าไม่สมบูรณ์สำหรับรายการ ID: {item_id}"}), 400

            # ดึงสต็อกปัจจุบันเพื่อตรวจสอบ
            current_qty = 0
            db_item = None
            if item_type == 'tire':
                db_item = database.get_tire(conn, item_id)
            elif item_type == 'wheel':
                db_item = database.get_wheel(conn, item_id)
            else:
                conn.rollback()
                return jsonify({"success": False, "message": f"ประเภทสินค้าไม่ถูกต้อง: {item_type}"}), 400
            
            if not db_item:
                conn.rollback()
                return jsonify({"success": False, "message": f"ไม่พบสินค้า ID {item_id} ในฐานข้อมูล"}), 404
            
            current_qty = db_item['quantity']

            new_qty = current_qty
            if transaction_type == 'IN':
                new_qty += quantity_change
            elif transaction_type == 'OUT':
                if current_qty < quantity_change:
                    conn.rollback() # สำคัญ: Rollback หากสต็อกไม่พอ
                    return jsonify({"success": False, "message": f"สต็อกไม่พอสำหรับ {db_item['brand'].title()} {db_item['model'].title()} (มีอยู่: {current_qty}, ต้องการ: {quantity_change})"}), 400
                new_qty -= quantity_change
            
            # อัปเดตสต็อกหลักในตาราง tires/wheels
            if item_type == 'tire':
                database.update_tire_quantity(conn, item_id, new_qty)
            elif item_type == 'wheel':
                database.update_wheel_quantity(conn, item_id, new_qty)
            
            # บันทึกการเคลื่อนไหวในตาราง tire_movements/wheel_movements
            if item_type == 'tire':
                database.add_tire_movement(conn, item_id, transaction_type, quantity_change, new_qty, notes, None, user_id)
            elif item_type == 'wheel':
                database.add_wheel_movement(conn, item_id, transaction_type, quantity_change, new_qty, notes, None, user_id)

        conn.commit() # ถ้าทุกรายการใน loop สำเร็จ ให้ commit transaction
        return jsonify({"success": True, "message": f"ทำรายการ {transaction_type} สำเร็จสำหรับ {len(items_to_process)} รายการ"}), 200

    except Exception as e:
        conn.rollback() # หากเกิดข้อผิดพลาดใดๆ ให้ rollback transaction ทั้งหมด
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการทำรายการ ระบบทำการย้อนกลับข้อมูล: {str(e)}"}), 500
        
        # app.py

# ... (โค้ดส่วนบน, imports, และ API Endpoints อื่นๆ เช่น api_scan_item_lookup, api_process_stock_transaction) ...

@app.route('/api/search_items_for_link', methods=['GET'])
@login_required
def api_search_items_for_link():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return jsonify({"success": False, "message": "กรุณาใส่คำค้นหา"}), 400

    conn = get_db()
    items = []

    # ค้นหายาง (Tires)
    # ใช้ LIKE เพื่อค้นหาส่วนหนึ่งของยี่ห้อ, รุ่น, หรือเบอร์ยาง
    tire_search_query = f"""
        SELECT id, brand, model, size, quantity AS current_quantity
        FROM tires
        WHERE is_deleted = FALSE AND (
            LOWER(brand) LIKE %s OR
            LOWER(model) LIKE %s OR
            LOWER(size) LIKE %s
        )
        ORDER BY brand, model, size
        LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor = conn.cursor()
        cursor.execute(tire_search_query, (f"%{query}%", f"%{query}%", f"%{query}%"))
    else:
        cursor = conn.execute(tire_search_query.replace('%s', '?'), (f"%{query}%", f"%{query}%", f"%{query}%"))
    
    for row in cursor.fetchall():
        item = dict(row)
        item['type'] = 'tire'
        items.append(item)

    # ค้นหาแม็ก (Wheels)
    wheel_search_query = f"""
        SELECT id, brand, model, diameter, pcd, width, quantity AS current_quantity
        FROM wheels
        WHERE is_deleted = FALSE AND (
            LOWER(brand) LIKE %s OR
            LOWER(model) LIKE %s OR
            LOWER(pcd) LIKE %s
        )
        ORDER BY brand, model, diameter
        LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(wheel_search_query, (f"%{query}%", f"%{query}%", f"%{query}%"))
    else:
        cursor = conn.execute(wheel_search_query.replace('%s', '?'), (f"%{query}%", f"%{query}%", f"%{query}%"))
    
    for row in cursor.fetchall():
        item = dict(row)
        item['type'] = 'wheel'
        items.append(item)

    return jsonify({"success": True, "items": items}), 200
    
@app.route('/api/link_barcode_to_item', methods=['POST'])
@login_required
def api_link_barcode_to_item():
    data = request.get_json()
    scanned_barcode = data.get('scanned_barcode')
    item_id = data.get('item_id') # ID ของยาง/แม็ก ที่ผู้ใช้เลือกจากหน้าค้นหา
    item_type = data.get('item_type') # 'tire' or 'wheel' (มาจาก frontend)

    if not scanned_barcode or not item_id or not item_type:
        return jsonify({"success": False, "message": "ข้อมูลไม่สมบูรณ์สำหรับการเชื่อมโยงบาร์โค้ด"}), 400

    conn = get_db()
    try:
        # ตรวจสอบว่า Barcode ID นี้มีอยู่ในระบบ tire_barcodes หรือ wheel_barcodes แล้วหรือยัง
        existing_tire_barcode_id = database.get_tire_id_by_barcode(conn, scanned_barcode)
        existing_wheel_barcode_id = database.get_wheel_id_by_barcode(conn, scanned_barcode)
        
        if existing_tire_barcode_id or existing_wheel_barcode_id:
            # ถ้ามีอยู่แล้วและผูกกับ item_id เดิม ก็ถือว่าสำเร็จ (ไม่ทำอะไร)
            if (item_type == 'tire' and existing_tire_barcode_id == item_id) or \
               (item_type == 'wheel' and existing_wheel_barcode_id == item_id):
                return jsonify({"success": True, "message": f"บาร์โค้ด '{scanned_barcode}' ถูกเชื่อมโยงกับสินค้านี้อยู่แล้ว"}), 200
            else:
                # ถ้ามีอยู่แล้วแต่ผูกกับ item_id อื่น แสดงว่าซ้ำซ้อน
                return jsonify({"success": False, "message": f"บาร์โค้ด '{scanned_barcode}' มีอยู่ในระบบแล้ว และถูกเชื่อมโยงกับสินค้าอื่น"}), 409

        # ถ้ายังไม่มีในระบบ ให้เพิ่มการเชื่อมโยงใหม่
        if item_type == 'tire':
            database.add_tire_barcode(conn, item_id, scanned_barcode, is_primary=False) # ตั้งเป็น False เพราะเป็นบาร์โค้ดทางเลือก
        elif item_type == 'wheel':
            database.add_wheel_barcode(conn, item_id, scanned_barcode, is_primary=False) # ตั้งเป็น False เพราะเป็นบาร์โค้ดทางเลือก
        else:
            conn.rollback()
            return jsonify({"success": False, "message": "ประเภทสินค้าไม่ถูกต้อง (ต้องเป็น tire หรือ wheel)"}), 400

        conn.commit()
        return jsonify({"success": True, "message": f"เชื่อมโยงบาร์โค้ด '{scanned_barcode}' กับสินค้าสำเร็จ!"}), 200

    except Exception as e:
        conn.rollback()
        # ตรวจสอบข้อผิดพลาดเฉพาะเจาะจงมากขึ้นหากจำเป็น (เช่น UNIQUE constraint failed)
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการเชื่อมโยงบาร์โค้ด: {str(e)}"}), 500

# --- Main entry point ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
