# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_file, current_app
import database
import pandas as pd
from io import BytesIO
from werkzeug.utils import secure_filename
import os
import sqlite3
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import re
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# *** เพิ่ม Cloudinary imports ***
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv # ถ้าใช้ python-dotenv สำหรับ local
load_dotenv() # โหลด environment variables จากไฟล์ .env สำหรับ local

app = Flask(__name__)
# **สำคัญมาก: เปลี่ยน 'your_super_secret_key_here_please_change_this_to_a_complex_random_random_string' เป็นคีย์ลับที่ซับซ้อนของคุณเอง!**
# คุณสามารถสร้างคีย์ลับที่ซับซ้อนได้โดยใช้ Python prompt:
# import os
# os.urandom(24).hex()
app.secret_key = os.environ.get('SECRET_KEY', 'your_super_secret_key_here_please_change_this_to_a_complex_random_string') # CHANGE THIS FOR PRODUCTION

app.config['UPLOAD_FOLDER'] = 'uploads' # สำหรับเก็บไฟล์ Excel และรูปภาพบิล (ถ้าไม่ใช้ Cloudinary)

# *** ตั้งค่า Cloudinary (ใช้ Environment Variables) ***
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True # ใช้ HTTPS
)

ALLOWED_EXCEL_EXTENSIONS = {'xlsx', 'xls'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

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

# **ถูกลบออกแล้ว:** ปรับปรุง setup_database ให้มีการเชื่อมต่อและ init_db อย่างถูกต้อง
# และเพิ่มการตรวจสอบว่า database มีการสร้างตาราง users หรือยัง
# def setup_database():
#     with app.app_context():
#         conn = get_db() # เรียก get_db เพื่อให้แน่ใจว่าเชื่อมต่อแล้ว
#         database.init_db(conn) # เรียก init_db เพื่อสร้างตารางถ้ายังไม่มี
        
#         # ตรวจสอบและสร้าง admin user เฉพาะถ้าตาราง users ยังไม่มีข้อมูล
#         try:
#             # ต้องสร้าง cursor เพื่อ execute query
#             cursor = conn.cursor()
#             cursor.execute("SELECT COUNT(*) FROM users")
#             user_count = cursor.fetchone()[0] # ดึงผลลัพธ์จาก cursor
            
#             if user_count == 0:
#                 admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
#                 admin_password = os.environ.get('ADMIN_PASSWORD', 'adminpassword')
#                 database.add_user(conn, admin_username, admin_password, role='admin')
#                 print(f"Initial admin user '{admin_username}' created with password '{admin_password}' and role 'admin'. PLEASE CHANGE THIS!")
#         except Exception as e:
#             # Log ข้อผิดพลาด แต่ไม่ raise เพื่อให้แอปทำงานต่อได้ในครั้งแรกที่ตารางยังไม่ถูกสร้าง
#             # ตารางจะถูกสร้างโดย init_db แต่ถ้า app.py รันก่อน init_db ทันทีอาจจะ fail
#             print(f"Warning: Error during initial user setup (table might not exist yet): {e}")
#             pass # ไม่ต้อง raise error เพื่อให้แอปทำงานได้

        # close_db() # ไม่ต้องเรียก close_db ตรงนี้ เพราะ @app.teardown_appcontext จะจัดการให้

def get_bkk_time():
    bkk_tz = pytz.timezone('Asia/Bangkok')
    return datetime.now(bkk_tz)

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
    
    # **แก้ไขตรงนี้**: ลบ database.init_db(conn) ออกจาก user_loader 
    # เพราะควรจะถูกจัดการโดย init_db.py หรือ setup_database ที่รันครั้งแรก
    # database.init_db(conn) # <-- ถูกลบออกแล้ว

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

# --- Protected Routes with @login_required ---
@app.route('/')
@login_required
def index():
    conn = get_db()

    tire_query = request.args.get('tire_query', '').strip()
    tire_selected_brand = request.args.get('tire_brand_filter', 'all').strip()

    all_tires = database.get_all_tires(conn, query=tire_query, brand_filter=tire_selected_brand)
    available_tire_brands = database.get_all_tire_brands(conn)

    tires_by_brand = defaultdict(list)
    for tire in all_tires:
        tires_by_brand[tire['brand']].append(tire)

    sorted_tire_brands = sorted(tires_by_brand.keys())

    wheel_query = request.args.get('wheel_query', '').strip()
    wheel_selected_brand = request.args.get('wheel_brand_filter', 'all').strip()

    all_wheels = database.get_all_wheels(conn, query=wheel_query, brand_filter=wheel_selected_brand)
    available_wheel_brands = database.get_all_wheel_brands(conn)

    wheels_by_brand = defaultdict(list)
    for wheel in all_wheels:
        wheels_by_brand[wheel['brand']].append(wheel)

    sorted_wheel_brands = sorted(wheels_by_brand.keys())

    active_tab = request.args.get('tab', 'tires')

    return render_template('index.html',
                           tires=all_tires,
                           tires_by_brand=tires_by_brand,
                           sorted_tire_brands=sorted_tire_brands,
                           tire_query=tire_query,
                           available_tire_brands=available_tire_brands,
                           tire_selected_brand=tire_selected_brand,

                           wheels_by_brand=wheels_by_brand,
                           sorted_wheel_brands=sorted_wheel_brands,
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
                elif promo_type == 'fixed_price_per_item' and value1 <= 0:
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
                elif promo_type == 'fixed_price_per_item' and value1 <= 0:
                    raise ValueError("ราคาพิเศษต้องมากกว่า 0")

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


# --- Tire Routes ---
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

        if submit_type == 'add_tire':
            brand = request.form['brand'].strip()
            model = request.form['model'].strip()
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
                                  year_of_manufacture)
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
            brand = request.form['brand'].strip()
            model = request.form['model'].strip()
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

                image_url = None # จะเก็บ URL ของรูปภาพจาก Cloudinary
                
                if image_file and image_file.filename != '': # ตรวจสอบว่ามีการเลือกไฟล์
                    if allowed_image_file(image_file.filename): # ตรวจสอบประเภทไฟล์
                        try:
                            # อัปโหลดรูปภาพไป Cloudinary
                            upload_result = cloudinary.uploader.upload(image_file)
                            image_url = upload_result['secure_url'] # Cloudinary จะคืน URL ของรูปภาพ
                            
                        except Exception as e:
                            flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพไปยัง Cloudinary: {e}', 'danger')
                            active_tab = 'wheel'
                            return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                    else:
                        flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                        active_tab = 'wheel'
                        return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
                
                # ส่ง image_url ไปยัง database.add_wheel
                database.add_wheel(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
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
        brand = request.form['brand'].strip()
        model = request.form['model'].strip()
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
            flash('ลบยางสำเร็จ!', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบยาง: {e}', 'danger')
    
    return redirect(url_for('index', tab='tires'))

# --- Wheel Routes ---
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

                current_image_url = wheel['image_filename'] # ดึง URL รูปภาพปัจจุบันจากฐานข้อมูล
                
                if image_file and image_file.filename != '': # ตรวจสอบว่ามีการเลือกไฟล์ใหม่
                    if allowed_image_file(image_file.filename):
                        try:
                            # อัปโหลดรูปภาพใหม่ไป Cloudinary
                            upload_result = cloudinary.uploader.upload(image_file)
                            new_image_url = upload_result['secure_url']
                            
                            # (ตัวเลือกเสริม: ลบรูปภาพเก่าจาก Cloudinary หากมีและต้องการลบ)
                            # ต้องใช้ public_id ในการลบ
                            if current_image_url and "res.cloudinary.com" in current_image_url:
                                # ดึง public_id จาก URL ของ Cloudinary
                                # รูปแบบ URL มักจะเป็น: .../v<version_num>/<public_id>.<extension>
                                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                                if public_id_match:
                                    public_id = public_id_match.group(1)
                                    try:
                                        cloudinary.uploader.destroy(public_id)
                                    except Exception as e:
                                        print(f"Error deleting old image from Cloudinary: {e}")
                            
                            current_image_url = new_image_url # อัปเดต URL เป็นรูปใหม่
                        
                        except Exception as e:
                            flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพไปยัง Cloudinary: {e}', 'danger')
                            return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)
                    else:
                        flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                        return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)
                # else: ถ้าไม่เลือกไฟล์ใหม่, current_image_url จะยังคงเป็นค่าเดิม (URL รูปภาพเก่า)

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
            # ลบรูปภาพจาก Cloudinary (ถ้ามี)
            if wheel['image_filename'] and "res.cloudinary.com" in wheel['image_filename']: # ตรวจสอบว่าเป็น URL ของ Cloudinary
                # ดึง public_id จาก URL Cloudinary
                public_id_match = re.search(r'v\d+/([^/.]+)', wheel['image_filename'])
                if public_id_match:
                    public_id = public_id_match.group(1)
                    try:
                        cloudinary.uploader.destroy(public_id) # ลบรูปภาพจาก Cloudinary
                    except Exception as e:
                        print(f"Error deleting image from Cloudinary: {e}") # แค่ Log error ไม่ต้องให้หยุด deletion จาก DB

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


# --- Stock Movement Routes ---
@app.route('/stock_movement', methods=('GET', 'POST'))
@login_required
def stock_movement():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการจัดการการเคลื่อนไหวสต็อก', 'danger')
        return redirect(url_for('index'))
    conn = get_db()

    tires = database.get_all_tires(conn)
    wheels = database.get_all_wheels(conn)
    
    # Get active_tab from request args, default to 'tire_movements'
    active_tab = request.args.get('tab', 'tire_movements') 

    # --- Fetch movements for BOTH tabs, regardless of active_tab ---
    # ดึงประวัติยาง 50 รายการล่าสุดเสมอ
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("SELECT tm.*, t.brand, t.model, t.size FROM tire_movements tm JOIN tires t ON tm.tire_id = t.id ORDER BY tm.timestamp DESC LIMIT 50")
    tire_movements_history = cursor.fetchall()

    # ดึงประวัติแม็ก 50 รายการล่าสุดเสมอ
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("SELECT wm.*, w.brand, w.model, w.diameter FROM wheel_movements wm JOIN wheels w ON wm.wheel_id = w.id ORDER BY wm.timestamp DESC LIMIT 50")
    wheel_movements_history = cursor.fetchall()

    # **แก้ไขเพิ่มเติม:** แปลง timestamp strings ให้เป็น datetime objects สำหรับ tire_movements_history
    processed_tire_movements_history = []
    for movement in tire_movements_history:
        m_dict = dict(movement) # Convert to dict to make it mutable
        if isinstance(m_dict['timestamp'], str):
            try:
                m_dict['timestamp'] = datetime.fromisoformat(m_dict['timestamp'])
            except ValueError:
                print(f"Warning: Could not parse timestamp string '{m_dict['timestamp']}' for tire movement ID {m_dict['id']}")
                m_dict['timestamp'] = None
        processed_tire_movements_history.append(m_dict)
    tire_movements_history = processed_tire_movements_history

    # **แก้ไขเพิ่มเติม:** แปลง timestamp strings ให้เป็น datetime objects สำหรับ wheel_movements_history
    processed_wheel_movements_history = []
    for movement in wheel_movements_history:
        m_dict = dict(movement) # Convert to dict to make it mutable
        if isinstance(m_dict['timestamp'], str):
            try:
                m_dict['timestamp'] = datetime.fromisoformat(m_dict['timestamp'])
            except ValueError:
                print(f"Warning: Could not parse timestamp string '{m_dict['timestamp']}' for wheel movement ID {m_dict['id']}")
                m_dict['timestamp'] = None
        processed_wheel_movements_history.append(m_dict)
    wheel_movements_history = processed_wheel_movements_history

    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        # Determine the active tab to redirect to after processing, useful for error cases
        active_tab_on_error = 'tire_movements' if submit_type == 'tire_movement' else 'wheel_movements'

        # กำหนด item_id_key และ quantity_form_key ตาม submit_type
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
            bill_image_file = request.files.get('bill_image') # รับไฟล์รูปภาพบิล

            bill_image_url_to_db = None # จะเก็บ URL ของรูปภาพจาก Cloudinary
            
            # *** ส่วนจัดการการอัปโหลดรูปภาพบิล (อัปโหลดขึ้น Cloudinary) ***
            if bill_image_file and bill_image_file.filename != '':
                if allowed_image_file(bill_image_file.filename):
                    try:
                        # อัปโหลดรูปภาพไป Cloudinary
                        upload_result = cloudinary.uploader.upload(bill_image_file)
                        bill_image_url_to_db = upload_result['secure_url'] # Cloudinary จะคืน URL ของรูปภาพ
                        
                    except Exception as e:
                        flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิลไปยัง Cloudinary: {e}', 'danger')
                        return redirect(url_for('stock_movement', tab=active_tab_on_error))
                else:
                    flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    return redirect(url_for('stock_movement', tab=active_tab_on_error))

            if quantity_change <= 0:
                flash('จำนวนที่เปลี่ยนแปลงต้องมากกว่า 0', 'danger')
                return redirect(url_for('stock_movement', tab=active_tab_on_error))
            
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
                # *** ส่ง bill_image_url_to_db ไปด้วย ***
                database.add_tire_movement(conn, tire_id, move_type, quantity_change, new_quantity, notes, bill_image_url_to_db)
                flash(f'บันทึกการเคลื่อนไหวสต็อกยางสำเร็จ! คงเหลือ: {new_quantity} เส้น', 'success')
                # Redirect to the tire movements tab
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
                # *** ส่ง bill_image_url_to_db ไปด้วย ***
                database.add_wheel_movement(conn, wheel_id, move_type, quantity_change, new_quantity, notes, bill_image_url_to_db)
                flash(f'บันทึกการเคลื่อนไหวสต็อกแม็กสำเร็จ! คงเหลือ: {new_quantity} วง', 'success')
                # Redirect to the wheel movements tab
                return redirect(url_for('stock_movement', tab='wheel_movements'))

        except ValueError:
            flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการบันทึกการเคลื่อนไหวสต็อก: {e}', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
    
    # Render the template with the correct history for the active tab
    return render_template('stock_movement.html', 
                           tires=tires, 
                           wheels=wheels, 
                           active_tab=active_tab,
                           tire_movements=tire_movements_history, 
                           wheel_movements=wheel_movements_history)

# --- New Routes for Editing Movements ---
@app.route('/edit_tire_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_tire_movement(movement_id):
    # อนุญาตเฉพาะ admin เท่านั้นที่แก้ไขได้
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกยาง', 'danger')
        return redirect(url_for('daily_stock_report'))

    conn = get_db()
    movement = database.get_tire_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        return redirect(url_for('daily_stock_report'))

    # Convert timestamp to datetime object if it's a string
    if isinstance(movement['timestamp'], str):
        try:
            # Adjust format to match how it's stored, e.g., 'YYYY-MM-DDTHH:MM:SS.f' for isoformat()
            # If your isoformat includes milliseconds, use '%Y-%m-%dT%H:%M:%S.%f'
            # If it's just 'YYYY-MM-DD HH:MM:SS', use that
            # For isoformat generated by get_bkk_time().isoformat(), it's usually 'YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM'
            # A more robust way to parse isoformat:
            movement = dict(movement) # Make it mutable if it's a Row object
            movement['timestamp'] = datetime.fromisoformat(movement['timestamp'])
        except ValueError:
            movement['timestamp'] = None # Fallback if parsing fails


    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement['image_filename'] # ตอนนี้จะเป็น URL ของ Cloudinary
        bill_image_url_to_db = current_image_url # เริ่มต้นด้วย URL ปัจจุบัน

        # จัดการการลบรูปภาพเก่าจาก Cloudinary
        if delete_existing_image:
            if current_image_url and "res.cloudinary.com" in current_image_url:
                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                if public_id_match:
                    public_id = public_id_match.group(1)
                    try:
                        cloudinary.uploader.destroy(public_id)
                    except Exception as e:
                        print(f"Error deleting old tire movement image from Cloudinary: {e}")
            bill_image_url_to_db = None # ตั้งค่าเป็น None หลังจากลบ

        # จัดการการอัปโหลดรูปภาพใหม่ไป Cloudinary
        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    upload_result = cloudinary.uploader.upload(bill_image_file)
                    new_image_url = upload_result['secure_url']
                    
                    # ถ้าอัปโหลดสำเร็จและมีรูปเก่าที่ยังไม่ถูกลบ (และเป็น Cloudinary URL)
                    # เราได้จัดการการลบไปแล้วในส่วน delete_existing_image
                    bill_image_url_to_db = new_image_url # อัปเดตเป็น URL ใหม่
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิลไปยัง Cloudinary: {e}', 'danger')
                    return render_template('edit_tire_movement.html', movement=movement)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                return render_template('edit_tire_movement.html', movement=movement)

        try:
            database.update_tire_movement(conn, movement_id, new_notes, bill_image_url_to_db)
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกยางสำเร็จ!', 'success')
            return redirect(url_for('daily_stock_report'))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')

    return render_template('edit_tire_movement.html', movement=movement)

@app.route('/edit_wheel_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_wheel_movement(movement_id):
    # อนุญาตเฉพาะ admin เท่านั้นที่แก้ไขได้
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกแม็ก', 'danger')
        return redirect(url_for('daily_stock_report'))

    conn = get_db()
    movement = database.get_wheel_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        return redirect(url_for('daily_stock_report'))

    # Convert timestamp to datetime object if it's a string
    if isinstance(movement['timestamp'], str):
        try:
            movement = dict(movement) # Make it mutable if it's a Row object
            movement['timestamp'] = datetime.fromisoformat(movement['timestamp'])
        except ValueError:
            movement['timestamp'] = None # Fallback if parsing fails

    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement['image_filename'] # ตอนนี้จะเป็น URL ของ Cloudinary
        bill_image_url_to_db = current_image_url # เริ่มต้นด้วย URL ปัจจุบัน

        # จัดการการลบรูปภาพเก่าจาก Cloudinary
        if delete_existing_image:
            if current_image_url and "res.cloudinary.com" in current_image_url:
                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                if public_id_match:
                    public_id = public_id_match.group(1)
                    try:
                        cloudinary.uploader.destroy(public_id)
                    except Exception as e:
                        print(f"Error deleting old wheel movement image from Cloudinary: {e}")
            bill_image_url_to_db = None # ตั้งค่าเป็น None หลังจากลบ

        # จัดการการอัปโหลดรูปภาพใหม่ไป Cloudinary
        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    upload_result = cloudinary.uploader.upload(bill_image_file)
                    new_image_url = upload_result['secure_url']
                    
                    # ถ้าอัปโหลดสำเร็จและมีรูปเก่าที่ยังไม่ถูกลบ (และเป็น Cloudinary URL)
                    # เราได้จัดการการลบไปแล้วในส่วน delete_existing_image
                    bill_image_url_to_db = new_image_url # อัปเดตเป็น URL ใหม่
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิลไปยัง Cloudinary: {e}', 'danger')
                    return render_template('edit_wheel_movement.html', movement=movement)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                return render_template('edit_wheel_movement.html', movement=movement)

        try:
            database.update_wheel_movement(conn, movement_id, new_notes, bill_image_url_to_db)
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกแม็กสำเร็จ!', 'success')
            return redirect(url_for('daily_stock_report'))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')

    return render_template('edit_wheel_movement.html', movement=movement)

# นี่คือฟังก์ชัน daily_stock_report ที่ถูกต้อง โดยมีข้อมูลการดึงและประมวลผลรายงานทั้งหมด
@app.route('/daily_stock_report')
@login_required
def daily_stock_report():
    conn = get_db()
    
    report_date_str = request.args.get('date')
    
    if report_date_str:
        try:
            report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
            display_date_str = report_date.strftime('%Y-%m-%d')
        except ValueError:
            flash("รูปแบบวันที่ไม่ถูกต้อง กรุณาใช้YYYY-MM-DD", "danger")
            report_date = get_bkk_time().date()
            display_date_str = report_date.strftime('%Y-%m-%d')
    else:
        report_date = get_bkk_time().date()
        display_date_str = report_date.strftime('%Y-%m-%d')

    sql_date_filter = report_date.strftime('%Y-%m-%d')


    # --- Tire Report Data ---
    # แก้ไข Query เพื่อดึง image_filename ด้วย
    tire_movements_query = f"""
        SELECT
            tm.id, tm.timestamp, tm.type, tm.quantity_change, tm.image_filename, tm.notes,
            t.id AS tire_main_id, t.brand, t.model, t.size
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        WHERE {database.get_sql_date_format_for_query('tm.timestamp')} = %s
        ORDER BY t.brand, t.model, t.size, tm.timestamp DESC
    """
    if "psycopg2" in str(type(conn)):
        # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
        cursor = conn.cursor()
        cursor.execute(tire_movements_query, (sql_date_filter,))
        tire_movements_raw = cursor.fetchall()
    else: # SQLite
        tire_movements_raw = conn.execute(tire_movements_query.replace('%s', '?'), (sql_date_filter,)).fetchall()

    # Convert timestamp strings to datetime objects for tire movements
    # Make sure items are mutable (e.g., dict) if they are sqlite3.Row objects
    processed_tire_movements_raw = []
    for movement in tire_movements_raw:
        m_dict = dict(movement) # Convert to dict to make it mutable
        if isinstance(m_dict['timestamp'], str):
            try:
                # Use fromisoformat for robust parsing of ISO 8601 strings
                # If your isoformat includes milliseconds, use '%Y-%m-%dT%H:%M:%S.%f'
                # For isoformat generated by get_bkk_time().isoformat(), it's usually 'YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM'
                # datetime.fromisoformat can handle optional timezone info
                m_dict['timestamp'] = datetime.fromisoformat(m_dict['timestamp'])
            except ValueError:
                # Fallback if the string format is not ISO 8601 or invalid
                print(f"Warning: Could not parse timestamp string '{m_dict['timestamp']}' for tire movement ID {m_dict['id']}")
                m_dict['timestamp'] = None # Or keep as string and handle in template with a filter
        processed_tire_movements_raw.append(m_dict)
    tire_movements_raw = processed_tire_movements_raw # Update the variable


    sorted_detailed_tire_report = []
    detailed_tire_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'remaining_quantity': 0})
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("SELECT id, quantity FROM tires")
    current_tire_quantities = cursor.fetchall()
    tire_current_qty_map = {t['id']: t['quantity'] for t in current_tire_quantities}

    for movement in tire_movements_raw: # ใช้ tire_movements_raw
        key = (movement['brand'], movement['model'], movement['size'])
        if movement['type'] == 'IN':
            detailed_tire_report[key]['IN'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            detailed_tire_report[key]['OUT'] += movement['quantity_change']
        # คำนวณ remaining_quantity อาจต้องใช้ข้อมูลจากปัจจุบัน หรือจาก movement ล่าสุด
        # ในที่นี้ใช้ quantity ณ ปัจจุบันของสินค้าแต่ละชิ้น (tire_current_qty_map)
        detailed_tire_report[key]['remaining_quantity'] = tire_current_qty_map.get(
            movement['tire_main_id'], 0
        )
    
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
    # แก้ไข Query เพื่อดึง image_filename ด้วย
    wheel_movements_query = f"""
        SELECT
            wm.id, wm.timestamp, wm.type, wm.quantity_change, wm.image_filename, wm.notes,
            w.id AS wheel_main_id, w.brand, w.model, w.diameter, w.pcd, w.width
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        WHERE {database.get_sql_date_format_for_query('wm.timestamp')} = %s
        ORDER BY w.brand, w.model, w.diameter, wm.timestamp DESC
    """
    if "psycopg2" in str(type(conn)):
        # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
        cursor = conn.cursor()
        cursor.execute(wheel_movements_query, (sql_date_filter,))
        wheel_movements_raw = cursor.fetchall()
    else: # SQLite
        wheel_movements_raw = conn.execute(wheel_movements_query.replace('%s', '?'), (sql_date_filter,)).fetchall()

    # Convert timestamp strings to datetime objects for wheel movements
    processed_wheel_movements_raw = []
    for movement in wheel_movements_raw:
        m_dict = dict(movement) # Convert to dict to make it mutable
        if isinstance(m_dict['timestamp'], str):
            try:
                # Use fromisoformat for robust parsing of ISO 8601 strings
                m_dict['timestamp'] = datetime.fromisoformat(m_dict['timestamp'])
            except ValueError:
                print(f"Warning: Could not parse timestamp string '{m_dict['timestamp']}' for wheel movement ID {m_dict['id']}")
                m_dict['timestamp'] = None # Or keep as string and handle in template with a filter
        processed_wheel_movements_raw.append(m_dict)
    wheel_movements_raw = processed_wheel_movements_raw # Update the variable


    sorted_detailed_wheel_report = []
    detailed_wheel_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'remaining_quantity': 0})
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("SELECT id, quantity FROM wheels")
    current_wheel_quantities = cursor.fetchall()
    wheel_current_qty_map = {w['id']: w['quantity'] for w in current_wheel_quantities}

    for movement in wheel_movements_raw: # ใช้ wheel_movements_raw
        key = (movement['brand'], movement['model'], movement['diameter'], movement['pcd'], movement['width'])
        if movement['type'] == 'IN':
            detailed_wheel_report[key]['IN'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            detailed_wheel_report[key]['OUT'] += movement['quantity_change']
        # คำนวณ remaining_quantity อาจต้องใช้ข้อมูลจากปัจจุบัน หรือจาก movement ล่าสุด
        # ในที่นี้ใช้ quantity ณ ปัจจุบันของสินค้าแต่ละชิ้น (wheel_current_qty_map)
        detailed_wheel_report[key]['remaining_quantity'] = wheel_current_qty_map.get(
            movement['wheel_main_id'], 0
        )

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
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(quantity) AS total_qty FROM tires")
    all_tires_in_stock = cursor.fetchone()[0] or 0

    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(quantity) AS total_qty FROM wheels")
    all_wheels_in_stock = cursor.fetchone()[0] or 0

    yesterday_date = report_date - timedelta(days=1)
    
    return render_template('daily_stock_report.html',
                           display_date_str=display_date_str,
                           report_date_param=report_date.strftime('%Y-%m-%d'),
                           yesterday_date_param=yesterday_date.strftime('%Y-%m-%d'),
                           
                           tire_report=sorted_detailed_tire_report,
                           wheel_report=sorted_detailed_wheel_report,
                           tire_total_in=tire_total_in,
                           tire_total_out=tire_total_out,
                           tire_total_remaining=all_tires_in_stock,
                           wheel_total_in=wheel_total_in,
                           wheel_total_out=wheel_total_out,
                           wheel_total_remaining=all_wheels_in_stock,
                           
                           # เพิ่มข้อมูล movement raw เพื่อใช้ในการแสดงผลและแก้ไข
                           tire_movements_raw=tire_movements_raw,
                           wheel_movements_raw=wheel_movements_raw
                          )

# --- Import/Export Routes ---
@app.route('/export_import', methods=('GET', 'POST'))
@login_required
def export_import():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการนำเข้า/ส่งออกข้อมูล', 'danger')
        return redirect(url_for('index'))
    conn = get_db() # **แก้ไข:** ต้องเรียก get_db() เพื่อให้ init_db ได้ทำงานก่อน
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
                    brand = str(row.get('ยี่ห้อ', '')).strip()
                    model = str(row.get('รุ่นยาง', '')).strip()
                    size = str(row.get('เบอร์ยาง', '')).strip()
                    
                    if not brand or not model or not size:
                        raise ValueError("ข้อมูล 'ยี่ห้อ', 'รุ่นยาง', หรือ 'เบอร์ยาง' ไม่สามารถเว้นว่างได้")

                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    price_per_item = float(row['ราคาต่อเส้น']) if pd.notna(row['ราคาต่อเส้น']) else 0.0

                    cost_sc = float(row['ทุน SC']) if pd.notna(row['ทุน SC']) else None
                    cost_dunlop = float(row['ทุน Dunlop']) if pd.notna(row['ทุน Dunlop']) else None
                    cost_online = float(row['ทุน Online']) if pd.notna(row['ทุน Online']) else None
                    wholesale_price1 = float(row['ราคาขายส่ง 1']) if pd.notna(row['ราคาขายส่ง 1']) else None
                    wholesale_price2 = float(row['ราคาขายส่ง 2']) if pd.notna(row['ราคาขายส่ง 2']) else None
                    
                    promotion_id = int(row.get('ID โปรโมชัน')) if pd.notna(row.get('ID โปรโมชัน')) else None
                    
                    year_of_manufacture = str(row['ปีผลิต']).strip() if pd.notna(row['ปีผลิต']) else None
                    
                    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, quantity FROM tires WHERE brand = %s AND model = %s AND size = %s", (brand, model, size))
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
                            database.add_tire_movement(conn, tire_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None) # ไม่มีรูปบิลจากการ Import
                        
                    else:
                        new_tire_id = database.add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                               promotion_id, year_of_manufacture)
                        database.add_tire_movement(conn, new_tire_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None) # ไม่มีรูปบิลจากการ Import
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
                    brand = str(row.get('ยี่ห้อ', '')).strip()
                    model = str(row.get('ลาย', '')).strip()
                    pcd = str(row.get('รู', '')).strip()

                    if not brand or not model or not pcd:
                            raise ValueError("ข้อมูล 'ยี่ห้อ', 'ลาย', หรือ 'รู' ไม่สามารถเว้นว่างได้")

                    diameter = float(row['ขอบ']) if pd.notna(row['ขอบ']) else 0.0
                    width = float(row['กว้าง']) if pd.notna(row['กว้าง']) else 0.0
                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    cost = float(row['ทุน']) if pd.notna(row['ทุน']) else None
                    retail_price = float(row['ราคาขายปลีก']) if pd.notna(row['ราคาขายปลีก']) else 0.0

                    et = int(row['ET']) if pd.notna(row['ET']) else None
                    color = str(row['สี']).strip() if pd.notna(row['สี']) else None
                    image_url = str(row['ไฟล์รูปภาพ']).strip() if pd.notna(row['ไฟล์รูปภาพ']) else None
                    cost_online = float(row['ทุน Online']) if pd.notna(row['ทุน Online']) else None
                    wholesale_price1 = float(row['ราคาขายส่ง 1']) if pd.notna(row['ราคาขายส่ง 1']) else None
                    wholesale_price2 = float(row['ราคาขายส่ง 2']) if pd.notna(row['ราคาขายส่ง 2']) else None
                    
                    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, quantity FROM wheels WHERE brand = %s AND model = %s AND diameter = %s AND pcd = %s AND width = %s AND (et IS %s OR et = %s) AND (color IS %s OR color = %s)", 
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
                            database.add_wheel_movement(conn, wheel_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None) # ไม่มีรูปบิลจากการ Import
                    else:
                        new_wheel_id = database.add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        database.add_wheel_movement(conn, new_wheel_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None) # ไม่มีรูปบิลจากการ Import
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
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
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
    # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = %s WHERE id = %s" if "psycopg2" in str(type(conn)) else "UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
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
        # **แก้ไข:** ต้องสร้าง cursor ก่อน execute
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s" if "psycopg2" in str(type(conn)) else "DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash('ลบผู้ใช้สำเร็จ!', 'success')
    return redirect(url_for('manage_users'))

# --- Main entry point ---
if __name__ == '__main__':
    setup_database()
    app.run(host='0.0.0.0', port=5000, debug=True)
