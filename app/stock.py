# -*- coding: utf-8 -*-
import qrcode
import qrcode.image.svg
import barcode
from barcode.writer import SVGWriter
import psycopg2
import sqlite3
from datetime import datetime, timedelta
import pytz
from collections import OrderedDict, defaultdict
import re
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, g, send_file, 
    current_app, jsonify, session, send_from_directory
)
import pandas as pd
from io import BytesIO
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
import os
import json
import document_generator
import uuid
import database
from database import get_bkk_time
from . import cache, api_key_required, get_db
from . import cache
from .utils import make_request
bp = Blueprint('stock', __name__)

# *** Add Cloudinary imports ***
import cloudinary
import cloudinary.uploader

ALLOWED_EXCEL_EXTENSIONS = {'xlsx', 'xls'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Define Bangkok timezone
BKK_TZ = pytz.timezone('Asia/Bangkok')

# --- Helper Functions (assuming these are already in your app.py) ---
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

def get_cached_wheels(query, brand_filter):
    all_wheels = get_all_wheels_list_cached()
    filtered_wheels = [
        w for w in all_wheels
        if (not query or \
            # เพิ่มเงื่อนไขนี้เข้าไปเพื่อค้นหาจากชื่อแบรนด์
            query.lower() in w.get('brand', '').lower() or \
            query.lower() in w.get('model', '').lower() or \
            query.lower() in str(w.get('diameter', '')).lower() or \
            query.lower() in w.get('pcd', '').lower() or \
            query.lower() in str(w.get('width', '')).lower() or \
            query.lower() in w.get('color', '').lower() or \
            query.lower() in str(w.get('et', '')).lower()
           )
        and (not brand_filter or brand_filter == 'all' or w.get('brand', '').lower() == brand_filter.lower())
    ]
    return filtered_wheels

@cache.memoize(timeout=900) # ข้อมูลยี่ห้อเปลี่ยนแปลงไม่บ่อย Cache ไว้นานขึ้นได้
def get_cached_tire_brands():
    print("--- CACHE MISS (TIRE BRANDS) --- Fetching tire brands from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_tire_brands(conn)

@cache.memoize(timeout=900) # ข้อมูลยี่ห้อเปลี่ยนแปลงไม่บ่อย Cache ไว้นานขึ้นได้
def get_cached_wheel_brands():
    print("--- CACHE MISS (WHEEL BRANDS) --- Fetching wheel brands from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_wheel_brands(conn)

def get_cached_tires(query, brand_filter):
    all_tires_raw = get_all_tires_list_cached()
    filtered_tires = [
        t for t in all_tires_raw
        if (not query or \
            query.lower() in t.get('brand', '').lower() or \
            query.lower() in t.get('model', '').lower() or \
            query.lower() in t.get('size', '').lower() \
           )
        and (not brand_filter or brand_filter == 'all' or t.get('brand', '').lower() == brand_filter.lower())
    ]
    return filtered_tires

@cache.memoize(timeout=300) # Cache 5 นาที
def get_cached_unread_notification_count():
    with current_app.app_context():
        conn = get_db()
        return database.get_unread_notification_count(conn)

#New Cache Logic ----- For Tire Wheel Spare

@cache.memoize(timeout=3600)
def get_all_spare_parts_cached():
    print(f"--- CACHE MISS (ALL SPARE PARTS) --- Fetching all spare parts from DB...")
    with current_app.app_context():
        conn = get_db()
        # เปลี่ยน None เป็น 'all' เพื่อให้ตรงกับเงื่อนไขการกรอง
        return database.get_all_spare_parts(conn, query=None, brand_filter='all', category_filter='all', include_deleted=False)

@cache.memoize(timeout=600)
def get_all_tires_list_cached():
    print("--- CACHE MISS (All Tires List) --- Fetching complete tire list from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_tires(conn, include_deleted=False)

@cache.memoize(timeout=600)
def get_all_wheels_list_cached():
    print("--- CACHE MISS (All Wheels List) --- Fetching complete wheel list from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_wheels(conn, include_deleted=False)

#---------------------------------------------------------#

def get_cached_spare_parts(query, brand_filter, category_filter):
    all_spare_parts = get_all_spare_parts_cached()
    filtered_parts = [
        p for p in all_spare_parts
        if (not query or query.lower() in p['name'].lower() or query.lower() in p['description'].lower() or query.lower() in p['part_number'].lower())
        and (not brand_filter or brand_filter == 'all' or p['brand'].lower() == brand_filter.lower())
        and (not category_filter or category_filter == 'all' or (isinstance(category_filter, list) and p['category_id'] in category_filter) or (isinstance(category_filter, str) and str(p['category_id']) == category_filter))
    ]
    return filtered_parts

@cache.memoize(timeout=900)
def get_cached_spare_part_brands(): # NEW
    print("--- CACHE MISS (SPARE PART BRANDS) --- Fetching spare part brands from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_spare_part_brands(conn)

@cache.memoize(timeout=900)
def get_cached_spare_part_categories_hierarchical():
    print("--- CACHE MISS (SPARE PART CATEGORIES) --- Fetching spare part categories hierarchically from DB")
    with current_app.app_context():
        conn = get_db()
        # ดึงข้อมูลทั้งหมดจากฐานข้อมูลในรูปแบบรายการแบบแบน (flat list)
        # ตรวจสอบว่า database.get_all_spare_part_categories ส่งคืน key เป็น 'name' หรือ 'name_display'
        # ถ้าส่งคืนเป็น 'name_display' อยู่แล้ว ก็ไม่ต้องแปลง
        categories_raw = database.get_all_spare_part_categories(conn)
        
        # ปรับโครงสร้างข้อมูลเล็กน้อยเพื่อให้มี key ที่ consistent
        categories = []
        for cat in categories_raw:
            # ใช้ name_display เป็นหลัก หรือใช้ name ถ้า name_display ไม่มี
            display_name = cat.get('name_display', cat.get('name'))
            if display_name: # ตรวจสอบให้แน่ใจว่ามีชื่อสำหรับแสดงผล
                categories.append({
                    'id': cat['id'],
                    'name_display': display_name, # ทำให้แน่ใจว่าใช้ 'name_display' ที่นี่
                    'parent_id': cat.get('parent_id') # ใช้ .get() เพื่อป้องกัน KeyError ถ้าไม่มี parent_id
                })
        
        # สร้างโครงสร้างข้อมูลแบบลำดับชั้น
        top_level_categories = []
        children_map = defaultdict(list)
        
        for cat in categories:
            if cat['parent_id'] is None:
                top_level_categories.append(cat)
            else:
                children_map[cat['parent_id']].append(cat)

        # เพิ่มหมวดหมู่ย่อยเข้าไปในหมวดหมู่หลัก
        for main_cat in top_level_categories:
            main_cat['children'] = children_map.get(main_cat['id'], [])
            
        return top_level_categories

@cache.memoize(timeout=86400) # Cache 3 ชั่วโมง
def get_all_sales_channels_cached():
    with current_app.app_context():
        conn = get_db()
        return database.get_all_sales_channels(conn)

@cache.memoize(timeout=86400)
def get_all_online_platforms_cached():
    with current_app.app_context():
        conn = get_db()
        return database.get_all_online_platforms(conn)

@cache.memoize(timeout=3600) # Cache 1 ชั่วโมง
def get_all_wholesale_customers_cached():
    with current_app.app_context():
        conn = get_db()
        return database.get_all_wholesale_customers(conn)

@cache.memoize(timeout=28800) # Cache 1 ชั่วโมง
def get_all_promotions_cached():
    print("--- CACHE MISS (Promotions) --- Fetching all promotions from DB")
    with current_app.app_context():
        conn = get_db()
    # ดึงมาทั้งหมด (รวม Inactive) เพื่อให้หน้าจัดการโปรโมชันใช้ได้ด้วย
        return database.get_all_promotions(conn, include_inactive=True)

# --- Helper function for processing report tables in app.py (for index and daily_stock_report) ---
def process_tire_report_data(all_tires, current_user_obj, include_summary_in_output=True):
    grouped_data = OrderedDict()
    brand_quantities = defaultdict(int)

    sorted_tires = sorted(all_tires, key=lambda x: (x['brand'], x['model'], x['size']))

    for tire in sorted_tires:
        # Ensure tire is a mutable dictionary for modifications
        tire_dict = dict(tire)

        # Get the original price_per_item (might be None if filtered by can_view_retail_price earlier)
        original_price_per_item = tire_dict.get('price_per_item')

        # Initialize display fields with default values (regular prices or None if not viewable)
        tire_dict['display_promo_price_per_item'] = None
        tire_dict['display_price_for_4'] = original_price_per_item * 4 if original_price_per_item is not None else None
        tire_dict['display_promo_description_text'] = None

        promo_active_check = tire_dict.get('promo_is_active')
        if isinstance(promo_active_check, int):
            promo_active_check = (promo_active_check == 1) # Convert SQLite boolean to Python boolean

        # Only apply promotion calculations if there's a promotion ID and it's active
        # AND if the original_price_per_item is not None (meaning user has retail price viewing rights)
        if tire_dict.get('promotion_id') is not None and promo_active_check and original_price_per_item is not None:
            promo_calc_result = database.calculate_tire_promo_prices(
                original_price_per_item, # Use the initial price for calculation
                tire_dict['promo_type'],
                tire_dict['promo_value1'],
                tire_dict['promo_value2']
            )

            # Apply specific logic based on user role
            if current_user_obj.is_retail_sales():
                # For 'retail_sales', hide promo price per item
                tire_dict['display_promo_price_per_item'] = None
                # Show the *calculated promotional price* for 4 tires
                tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
                # Show promo description
                tire_dict['display_promo_description_text'] = promo_calc_result['promo_description_text']
            else:
                # For other roles (admin, editor) who can view retail prices, show the calculated promo prices
                tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
                tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
                tire_dict['display_promo_description_text'] = promo_calc_result['promo_description_text']
        # If no active promotion, or original_price_per_item is None,
        # display_promo_price_per_item and display_promo_description_text remain None,
        # and display_price_for_4 remains the regular price (or None if not viewable).

        brand = tire_dict['brand']
        # ถ้ายังไม่มีแบรนด์นี้ใน grouped_data ให้สร้าง entry ใหม่
        if brand not in grouped_data:
            grouped_data[brand] = {'items_list': [], 'summary': {}} # เปลี่ยนชื่อเป็น items_list

        # เพิ่มรายการยางลงใน 'items_list'
        grouped_data[brand]['items_list'].append({
            'is_summary': False,
            'brand': tire_dict['brand'],
            'model': tire_dict['model'],
            'size': tire_dict['size'],
            'quantity': tire_dict['quantity'],
            'price_per_item': tire_dict['price_per_item'], # Original price_per_item
            'promotion_id': tire_dict['promotion_id'],
            'promo_is_active': tire_dict['promo_is_active'],
            'promo_name': tire_dict['promo_name'],
            'display_promo_description_text': tire_dict['display_promo_description_text'],
            'display_promo_price_per_item': tire_dict['display_promo_price_per_item'],
            'display_price_for_4': tire_dict['display_price_for_4'], # This will be the promo price for retail_sales if active, else regular
            'year_of_manufacture': tire_dict['year_of_manufacture'],
            'id': tire_dict['id'],
            # NEW: เพิ่มฟิลด์ cost_sc, cost_dunlop, cost_online เข้าไปใน dictionary ที่จะส่งให้ template
            'cost_sc': tire_dict.get('cost_sc'),
            'cost_dunlop': tire_dict.get('cost_dunlop'),
            'cost_online': tire_dict.get('cost_online'),
            'wholesale_price1': tire_dict.get('wholesale_price1'),
            'wholesale_price2': tire_dict.get('wholesale_price2')
        })
        brand_quantities[brand] += tire_dict['quantity']

    for brand, data in grouped_data.items():
        data['summary'] = {
            'is_summary': True,
            'is_summary_to_show': include_summary_in_output,
            'brand': brand,
            'quantity': brand_quantities[brand],
            'formatted_quantity': f'<span class="summary-quantity-value">{brand_quantities[brand]}</span>' # type: ignore
            }
    return grouped_data
        

# MODIFIED: Adjust return data structure in process_wheel_report_data
def process_wheel_report_data(all_wheels, include_summary_in_output=True):
    grouped_data = OrderedDict()
    brand_quantities = defaultdict(int)

    sorted_wheels = sorted(all_wheels, key=lambda x: (x['brand'], x['model'], x['diameter'], x['width'], x['pcd']))

    for wheel in sorted_wheels:
        brand = wheel['brand']
        if brand not in grouped_data:
            grouped_data[brand] = {'items_list': [], 'summary': {}}

        grouped_data[brand]['items_list'].append({
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
            'id': wheel['id'],
            # ตรวจสอบให้แน่ใจว่า cost_online, wholesale_price1, wholesale_price2 ถูกส่งผ่านด้วย
            'cost_online': wheel.get('cost_online'),
            'wholesale_price1': wheel.get('wholesale_price1'),
            'wholesale_price2': wheel.get('wholesale_price2')
        })
        brand_quantities[brand] += int(wheel.get('quantity') or 0)

    for brand, data in grouped_data.items():
        data['summary'] = {
            'is_summary': True,
            'is_summary_to_show': include_summary_in_output,
            'brand': brand,
            'quantity': brand_quantities[brand],
            'formatted_quantity': f'<span class="summary-quantity-value">{brand_quantities[brand]}</span>' # type: ignore
        }
    return grouped_data

# NEW: Helper function for processing spare parts data
def process_spare_part_report_data(all_spare_parts, include_summary_in_output=True):
    grouped_data = OrderedDict()
    category_quantities = defaultdict(int)
    brand_quantities = defaultdict(int) # สามารถสรุปตามแบรนด์ได้ด้วย

    # เรียงตามหมวดหมู่ก่อน จากนั้นค่อยตามแบรนด์และชื่ออะไหล่
    sorted_parts = sorted(all_spare_parts, key=lambda x: (x['category_name'] or '', x['brand'] or '', x['name']))

    for part in sorted_parts:
        category_name = part['category_name'] or 'ไม่ระบุหมวดหมู่'
        brand = part['brand'] or 'ไม่ระบุยี่ห้อ' # ใช้ brand สำหรับการรวมย่อย

        # จัดกลุ่มหลักตามหมวดหมู่
        if category_name not in grouped_data:
            grouped_data[category_name] = {'brands': OrderedDict(), 'summary': {}}

        # ภายในหมวดหมู่ จัดกลุ่มย่อยตามแบรนด์
        if brand not in grouped_data[category_name]['brands']:
            grouped_data[category_name]['brands'][brand] = {'items_list': [], 'summary': {}}

        grouped_data[category_name]['brands'][brand]['items_list'].append({
            'is_summary': False,
            'id': part['id'],
            'name': part['name'],
            'part_number': part['part_number'],
            'brand': part['brand'],
            'description': part['description'],
            'quantity': part['quantity'],
            'cost': part['cost'],
            'retail_price': part['retail_price'],
            'wholesale_price1': part.get('wholesale_price1'),
            'wholesale_price2': part.get('wholesale_price2'),
            'cost_online': part.get('cost_online'),
            'image_filename': part['image_filename'],
            'category_name': part['category_name']
        })
        category_quantities[category_name] += part['quantity']
        brand_quantities[f"{category_name}|{brand}"] += part['quantity'] # ใช้ key ผสมสำหรับ brand_quantities

    # คำนวณ summary สำหรับแต่ละ brand ภายใน category
    for cat_name, cat_data in grouped_data.items():
        for brand_name, brand_data in cat_data['brands'].items():
            brand_data['summary'] = {
                'is_summary': True,
                'is_summary_to_show': include_summary_in_output,
                'type': 'brand_summary',
                'brand': brand_name,
                'quantity': brand_quantities[f"{cat_name}|{brand_name}"],
                'formatted_quantity': f'<span class="summary-quantity-value">{brand_quantities[f"{cat_name}|{brand_name}"]}</span>'
            }

        # คำนวณ summary สำหรับแต่ละ category
        cat_data['summary'] = {
            'is_summary': True,
            'is_summary_to_show': include_summary_in_output,
            'type': 'category_summary',
            'category': cat_name,
            'quantity': category_quantities[cat_name],
            'formatted_quantity': f'<span class="summary-quantity-value">{category_quantities[cat_name]}</span>'
        }

    return grouped_data


@bp.route('/')
@login_required
def index():
    conn = get_db()
    today = get_bkk_time().date()

    tire_query = request.args.get('tire_query', '').strip()
    tire_selected_brand = request.args.get('tire_brand_filter', 'all').strip()
    is_tire_search_active = bool(tire_query or (tire_selected_brand and tire_selected_brand != 'all'))
    all_tires_raw = get_cached_tires(tire_query, tire_selected_brand)
    available_tire_brands = get_cached_tire_brands()
    todays_commissions_raw = database.get_commission_programs_for_date(conn, today)
    todays_commissions = {f"{p['item_type']}-{p['item_id']}": p['commission_amount_per_item'] for p in todays_commissions_raw}


    # NEW: Filter tire data based on viewing permissions before sending to template
    tires_for_display_filtered_by_permissions = []
    for tire_data in all_tires_raw:
        filtered_tire = dict(tire_data) # Create a copy to modify
        if not current_user.can_view_cost(): # If no permission to view cost
            filtered_tire['cost_sc'] = None
            filtered_tire['cost_dunlop'] = None
            filtered_tire['cost_online'] = None
        if not current_user.can_view_wholesale_price_1():
            filtered_tire['wholesale_price1'] = None
        if not current_user.can_view_wholesale_price_2():
            filtered_tire['wholesale_price2'] = None

        # NOTE: Logic for hiding retail price and promotions for 'wholesale_sales' and 'viewer' roles
        # will be handled in process_tire_report_data using current_user.can_view_retail_price()
        # and current_user.is_retail_sales() together.
        if not current_user.can_view_retail_price():
            filtered_tire['price_per_item'] = None
            # Clear all promotion data if retail price cannot be viewed
            filtered_tire['promotion_id'] = None
            filtered_tire['promo_is_active'] = None
            filtered_tire['promo_name'] = None
            filtered_tire['promo_type'] = None
            filtered_tire['promo_value1'] = None
            filtered_tire['promo_value2'] = None
            filtered_tire['display_promo_description_text'] = None
            filtered_tire['display_promo_price_per_item'] = None
            filtered_tire['display_price_for_4'] = None
        tires_for_display_filtered_by_permissions.append(filtered_tire) #

    # Pass current_user object to process_tire_report_data
    tires_by_brand_for_display = process_tire_report_data(
        tires_for_display_filtered_by_permissions,
        current_user, # Pass the current_user object
        include_summary_in_output=is_tire_search_active
    )

    wheel_query = request.args.get('wheel_query', '').strip()
    wheel_selected_brand = request.args.get('wheel_brand_filter', 'all').strip()
    is_wheel_search_active = bool(wheel_query or (wheel_selected_brand and wheel_selected_brand != 'all'))
    all_wheels = get_cached_wheels(wheel_query, wheel_selected_brand)
    available_wheel_brands = get_cached_wheel_brands()

    # NEW: Filter wheel data based on viewing permissions before sending to template
    wheels_for_display = []
    for wheel_data in all_wheels:
        filtered_wheel = dict(wheel_data) # Create a copy to modify
        if not current_user.can_view_cost(): # If no permission to view cost
            filtered_wheel['cost'] = None
            filtered_wheel['cost_online'] = None
        if not current_user.can_view_wholesale_price_1():
            filtered_wheel['wholesale_price1'] = None
        if not current_user.can_view_wholesale_price_2():
            filtered_wheel['wholesale_price2'] = None
        if not current_user.can_view_retail_price(): # If no permission to view retail price
            filtered_wheel['retail_price'] = None
        wheels_for_display.append(filtered_wheel) #

    wheels_by_brand_for_display = process_wheel_report_data(wheels_for_display, include_summary_in_output=is_wheel_search_active)

    # NEW: Spare Part data for index page
    spare_part_query = request.args.get('spare_part_query', '').strip()
    spare_part_selected_brand = request.args.get('spare_part_brand_filter', 'all').strip()
    spare_part_selected_category = request.args.get('spare_part_category_filter', 'all').strip()

    is_spare_part_search_active = bool(spare_part_query or
                                       (spare_part_selected_brand and spare_part_selected_brand != 'all') or
                                       (spare_part_selected_category and spare_part_selected_category != 'all'))

    available_spare_part_categories = get_cached_spare_part_categories_hierarchical()
    if spare_part_selected_category and spare_part_selected_category != 'all':
        selected_category_id = int(spare_part_selected_category)
        category_ids_to_filter = [selected_category_id]
    
        # ตรวจสอบและเพิ่ม ID ของหมวดหมู่ย่อย
        for main_cat in available_spare_part_categories:
            if main_cat.get('id') == selected_category_id:
                for sub_cat in main_cat.get('children', []):
                    category_ids_to_filter.append(sub_cat.get('id'))
                break
    else:
        # หากไม่ได้เลือกหมวดหมู่ใด ๆ ให้ใช้ 'all'
        category_ids_to_filter = 'all'
    
    all_spare_parts_raw = get_cached_spare_parts(spare_part_query, spare_part_selected_brand, category_ids_to_filter)
    available_spare_part_brands = get_cached_spare_part_brands()

    # Filter spare part data based on viewing permissions
    spare_parts_for_display = []
    for part_data in all_spare_parts_raw:
        filtered_part = dict(part_data)
        if not current_user.can_view_cost():
            filtered_part['cost'] = None
            filtered_part['cost_online'] = None
        if not current_user.can_view_wholesale_price_1():
            filtered_part['wholesale_price1'] = None
        if not current_user.can_view_wholesale_price_2():
            filtered_part['wholesale_price2'] = None
        if not current_user.can_view_retail_price():
            filtered_part['retail_price'] = None
        spare_parts_for_display.append(filtered_part)

    spare_parts_by_category_and_brand = process_spare_part_report_data(
        spare_parts_for_display,
        include_summary_in_output=is_spare_part_search_active
    )


    active_tab = request.args.get('tab', 'tires')

    spare_parts_by_brand_by_category = process_spare_part_report_data(spare_parts_for_display)
    return render_template('index.html',
                           tires_by_brand_for_display=tires_by_brand_for_display,      
                           wheels_by_brand_for_display=wheels_by_brand_for_display,                   
                           tire_query=tire_query,
                           available_tire_brands=available_tire_brands,
                           todays_commissions=todays_commissions, # NEW
                           tire_selected_brand=tire_selected_brand, 
                           wheel_query=wheel_query,
                           available_wheel_brands=available_wheel_brands,
                           wheel_selected_brand=wheel_selected_brand,
                           is_spare_part_search_active=is_spare_part_search_active,
                           spare_parts_by_category_and_brand=spare_parts_by_category_and_brand,
                           spare_part_query=spare_part_query,
                           available_spare_part_brands=available_spare_part_brands,
                           spare_part_selected_brand=spare_part_selected_brand,
                           available_spare_part_categories=available_spare_part_categories,
                           spare_part_selected_category=spare_part_selected_category,
                           active_tab=active_tab,
                           current_user=current_user # Pass current_user to template
                          )

# --- Promotions Routes (assuming these are already in your app.py) ---
@bp.route('/promotions')
@login_required
def promotions():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการจัดการโปรโมชัน', 'danger')
        return redirect(url_for('stock.index'))
        
    conn = get_db()
    all_promotions = get_all_promotions_cached()
    return render_template('promotions.html', promotions=all_promotions, current_user=current_user)

@bp.route('/add_promotion', methods=('GET', 'POST'))
@login_required
def add_promotion():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการเพิ่มโปรโมชัน', 'danger')
        return redirect(url_for('stock.promotions'))
        
    if request.method == 'POST':
        name = request.form['name'].strip()
        promo_type = request.form['type'].strip()
        value1 = request.form['value1'].strip()
        value2 = request.form.get('value2', '').strip()
        is_active = request.form.get('is_active') == '1'

        if not name or not promo_type or not value1:
            flash('กรุณากรอกข้อมูลโปรโมชันให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
            conn = get_db()
            conn.rollback()
            return render_template('add_promotion.html', current_user=current_user)
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
                conn.commit()
                flash('เพิ่มโปรโมชันใหม่สำเร็จ!', 'success')
                cache.delete_memoized(get_all_promotions_cached)
                return redirect(url_for('stock.promotions'))
            except ValueError as e:
                conn.rollback()
                flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ชื่อโปรโมชัน "{name}" มีอยู่ในระบบแล้ว', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มโปรโมชัน: {e}', 'danger')

    return render_template('add_promotion.html', current_user=current_user)

@bp.route('/edit_promotion/<int:promo_id>', methods=('GET', 'POST'))
@login_required
def edit_promotion(promo_id):
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการแก้ไขโปรโมชัน', 'danger')
        return redirect(url_for('stock.promotions'))
        
    conn = get_db()
    promotion = database.get_promotion(conn, promo_id)

    if promotion is None:
        flash('ไม่พบโปรโมชันที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.promotions'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        promo_type = request.form['type'].strip()
        value1 = request.form['value1'].strip()
        value2 = request.form.get('value2', '').strip()
        is_active = request.form.get('is_active') == '1'

        if not name or not promo_type or not value1:
            flash('กรุณากรอกข้อมูลโปรโมชันให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
            conn.rollback()
            return render_template('edit_promotion.html', promotion=promotion, current_user=current_user)
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
                conn.commit()
                flash('แก้ไขโปรโมชันสำเร็จ!', 'success')
                cache.delete_memoized(get_all_promotions_cached)
                return redirect(url_for('stock.promotions'))
            except ValueError as e:
                conn.rollback()
                flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ชื่อโปรโมชัน "{name}" มีอยู่ในระบบแล้ว', 'warning')
                else:
                    conn.rollback()
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขโปรโมชัน: {e}', 'danger')

    return render_template('edit_promotion.html', promotion=promotion, current_user=current_user)

@bp.route('/delete_promotion/<int:promo_id>', methods=('POST',))
@login_required
def delete_promotion(promo_id):
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการลบโปรโมชัน', 'danger')
        return redirect(url_for('stock.promotions'))
        
    conn = get_db()
    promotion_to_delete = database.get_promotion(conn, promo_id)

    if promotion_to_delete is None:
        conn.rollback()
        flash('ไม่พบโปรโมชันที่ระบุ', 'danger')
    else:
        try:
            database.delete_promotion(conn, promo_id)
            conn.commit()
            flash('ลบโปรโมชันสำเร็จ! สินค้าที่เคยใช้โปรโมชันนี้จะถูกตั้งค่าโปรโมชันเป็น "ไม่มี"', 'success')
            cache.delete_memoized(get_all_promotions_cached)
            cache.delete_memoized(get_all_tires_list_cached)
        except Exception as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาดในการลบโปรโมชัน: {e}', 'danger')

    return redirect(url_for('stock.promotions'))


# --- Item Management Routes (Add/Edit/Delete) (assuming these are already in your app.py) ---
@bp.route('/add_item', methods=('GET', 'POST'))
@login_required
def add_item():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการเพิ่มสินค้า', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    current_year = get_bkk_time().year
    form_data = None
    active_tab = request.args.get('tab', 'tire')
    scanned_barcode_for_add = request.args.get('barcode_id_for_add', '')

    all_promotions = get_all_promotions_cached()
    # NEW: สำหรับอะไหล่
    all_spare_part_categories = get_cached_spare_part_categories_hierarchical()


    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        form_data = request.form

        current_user_id = current_user.id if current_user.is_authenticated else None

        if submit_type == 'add_tire':
            brand = request.form['brand'].strip().lower()
            model = request.form['model'].strip().lower()
            size = request.form['size'].strip()
            quantity = request.form['quantity']

            scanned_barcode_for_add = request.form.get('barcode_id_for_add', '').strip()

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
                conn.rollback()
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

            if scanned_barcode_for_add:
                existing_barcode_tire_id = database.get_tire_id_by_barcode(conn, scanned_barcode_for_add)
                existing_barcode_wheel_id = database.get_wheel_id_by_barcode(conn, scanned_barcode_for_add)
                existing_barcode_spare_part_id = database.get_spare_part_id_by_barcode(conn, scanned_barcode_for_add) # NEW
                if existing_barcode_tire_id or existing_barcode_wheel_id or existing_barcode_spare_part_id: # NEW
                    flash(f"Barcode ID '{scanned_barcode_for_add}' มีอยู่ในระบบแล้ว. ไม่สามารถใช้ซ้ำได้.", 'danger')
                    conn.rollback()
                    active_tab = 'tire'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

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
                    conn.rollback()
                else:
                    new_tire_id = database.add_tire(conn, brand, model, size, quantity,
                                                    cost_sc, cost_dunlop, cost_online,
                                                    wholesale_price1, wholesale_price2,
                                                    price_per_item, promotion_id_db,
                                                    year_of_manufacture,
                                                    user_id=current_user_id)
                    if scanned_barcode_for_add:
                        database.add_tire_barcode(conn, new_tire_id, scanned_barcode_for_add, is_primary=True)
                    conn.commit()
                    flash(f'เพิ่มยาง {brand.title()} รุ่น {model.title()} เบอร์ {size} จำนวน {quantity} เส้น สำเร็จ!', 'success')
                    cache.delete_memoized(get_cached_tire_brands)
                    cache.delete_memoized(get_all_tires_list_cached)
                return redirect(url_for('stock.add_item', tab='tire'))

            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: ข้อมูลซ้ำซ้อนในระบบ หรือ Barcode ID นี้มีอยู่แล้ว. รายละเอียด: {e}', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มยาง: {e}', 'danger')
                    conn.rollback()
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)


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
            image_url = None # Set initial value

            # --- START: MODIFIED UPLOAD LOGIC ---
            if image_file and image_file.filename != '':
                if not allowed_image_file(image_file.filename):
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    conn.rollback()
                    active_tab = 'wheel'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

                try:
                    if current_app.config['CLOUDINARY_AVAILABLE']:
                        # Use Cloudinary
                        upload_result = cloudinary.uploader.upload(image_file)
                        image_url = upload_result['secure_url']
                    else:
                        # Use local storage
                        original_filename = secure_filename(image_file.filename)
                        file_extension = os.path.splitext(original_filename)[1]
                        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                        
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                        image_file.save(filepath)
                        image_url = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพ: {e}', 'danger')
                    conn.rollback()
                    active_tab = 'wheel'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)
            # --- END: MODIFIED UPLOAD LOGIC ---


            if not brand or not model or not pcd or not diameter or not width or not quantity or not retail_price:
                flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                conn.rollback()
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

            if scanned_barcode_for_add:
                existing_barcode_tire_id = database.get_tire_id_by_barcode(conn, scanned_barcode_for_add)
                existing_barcode_wheel_id = database.get_wheel_id_by_barcode(conn, scanned_barcode_for_add)
                existing_barcode_spare_part_id = database.get_spare_part_id_by_barcode(conn, scanned_barcode_for_add) # NEW
                if existing_barcode_tire_id or existing_barcode_wheel_id or existing_barcode_spare_part_id: # NEW
                    flash(f"Barcode ID '{scanned_barcode_for_add}' มีอยู่ในระบบแล้ว. ไม่สามารถใช้ซ้ำได้.", 'danger')
                    conn.rollback()
                    active_tab = 'wheel'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

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

                cursor = conn.cursor()
                if "psycopg2" in str(type(conn)):
                    cursor.execute("""
                        SELECT id FROM wheels WHERE brand = %s AND model = %s AND diameter = %s 
                        AND width = %s AND pcd = %s AND color = %s AND et IS NOT DISTINCT FROM %s
                    """, (brand, model, diameter, width, pcd, color, et))
                else:
                    cursor.execute("""
                        SELECT id FROM wheels WHERE brand = ? AND model = ? AND diameter = ? 
                        AND width = ? AND pcd = ? AND color = ? AND et = ?
                    """, (brand, model, diameter, width, pcd, color, et))

                existing_wheel = cursor.fetchone()

                if existing_wheel:
                    flash(f'แม็ก {brand.title()} ลาย {model.title()} สี {color} ขนาด {diameter}x{width} มีอยู่ในระบบแล้ว', 'warning')
                    conn.rollback()
                else:
                    new_wheel_id = database.add_wheel(conn, brand, model, diameter, pcd, width, et, color,
                                                    quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, user_id=current_user.id)
                    if scanned_barcode_for_add:
                        database.add_wheel_barcode(conn, new_wheel_id, scanned_barcode_for_add, is_primary=True)
                    conn.commit()
                    flash(f'เพิ่มแม็ก {brand.title()} ลาย {model.title()} จำนวน {quantity} วง สำเร็จ!', 'success')
                    cache.delete_memoized(get_cached_wheel_brands)
                    cache.delete_memoized(get_all_wheels_list_cached)
                return redirect(url_for('stock.index', tab='wheels'))
            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: ข้อมูลซ้ำซ้อนในระบบ หรือ Barcode ID นี้มีอยู่แล้ว. รายละเอียด: {e}', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มแม็ก: {e}', 'danger')
                    conn.rollback()
                active_tab = 'wheel'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

        # NEW: Logic for adding Spare Parts
        elif submit_type == 'add_spare_part':
            name = request.form['name'].strip()
            part_number = request.form.get('part_number', '').strip()
            brand = request.form.get('brand', '').strip().lower()
            description = request.form.get('description', '').strip()
            quantity = request.form['quantity']
            retail_price = request.form['retail_price']
            category_id = request.form.get('category_id') # NEW: รับ category_id

            scanned_barcode_for_add = request.form.get('barcode_id_for_add', '').strip()

            cost = request.form.get('cost')
            cost_online = request.form.get('cost_online')
            wholesale_price1 = request.form.get('wholesale_price1')
            wholesale_price2 = request.form.get('wholesale_price2')

            image_file = request.files.get('image_file')
            image_url = None

            if not name or not quantity or not retail_price:
                flash('กรุณากรอกข้อมูลอะไหล่ให้ครบถ้วนในช่องที่มีเครื่องหมาย * (ชื่อ, จำนวน, ราคาขายปลีก)', 'danger')
                conn.rollback()
                active_tab = 'spare_part'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

            if category_id == 'none' or not category_id: # Check if category is selected
                category_id_db = None
            else:
                category_id_db = int(category_id)

            # --- START: MODIFIED UPLOAD LOGIC ---
            if image_file and image_file.filename != '':
                if not allowed_image_file(image_file.filename):
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    conn.rollback()
                    active_tab = 'spare_part'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

                try:
                    if current_app.config['CLOUDINARY_AVAILABLE']:
                        # Use Cloudinary
                        upload_result = cloudinary.uploader.upload(image_file)
                        image_url = upload_result['secure_url']
                    else:
                        # Use local storage
                        original_filename = secure_filename(image_file.filename)
                        file_extension = os.path.splitext(original_filename)[1]
                        unique_filename = f"{uuid.uuid4().hex}{file_extension}"

                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                        image_file.save(filepath)
                        image_url = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพ: {e}', 'danger')
                    conn.rollback()
                    active_tab = 'spare_part'
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)
            # --- END: MODIFIED UPLOAD LOGIC ---

            try:
                quantity = int(quantity)
                retail_price = float(retail_price)

                cost = float(cost) if cost and cost.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None

                cursor = conn.cursor()
                is_postgres = "psycopg2" in str(type(conn))

                # Check for existing spare part by name and (optional) part_number/brand
                if part_number: # Prefer part_number if provided for uniqueness
                    if is_postgres:
                        cursor.execute("SELECT id FROM spare_parts WHERE name = %s AND part_number = %s", (name, part_number))
                    else:
                        cursor.execute("SELECT id FROM spare_parts WHERE name = ? AND part_number = ?", (name, part_number))
                else: # Fallback to just name and brand if no part_number
                    if is_postgres:
                        cursor.execute("SELECT id FROM spare_parts WHERE name = %s AND brand = %s", (name, brand))
                    else:
                        cursor.execute("SELECT id FROM spare_parts WHERE name = ? AND brand = ?", (name, brand))

                existing_spare_part = cursor.fetchone()

                if existing_spare_part:
                    flash(f'อะไหล่ "{name}" (Part No: {part_number if part_number else "N/A"}) มีอยู่ในระบบแล้ว', 'warning')
                    conn.rollback()
                else:
                    new_spare_part_id = database.add_spare_part(conn, name, part_number, brand, description, quantity,
                                                                 cost, retail_price, wholesale_price1, wholesale_price2,
                                                                 cost_online, image_url, category_id_db, user_id=current_user_id)
                    if scanned_barcode_for_add:
                        database.add_spare_part_barcode(conn, new_spare_part_id, scanned_barcode_for_add, is_primary=True)
                    conn.commit()
                    flash(f'เพิ่มอะไหล่ "{name}" จำนวน {quantity} ชิ้น สำเร็จ!', 'success')
                    cache.delete_memoized(get_all_spare_parts_cached)
                    cache.delete_memoized(get_cached_spare_part_brands)
                return redirect(url_for('stock.add_item', tab='spare_part'))

            except ValueError as e:
                conn.rollback()
                flash(f'ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ: {e}', 'danger')
                active_tab = 'spare_part'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: รหัสอะไหล่หรือชื่อซ้ำซ้อนในระบบ หรือ Barcode ID นี้มีอยู่แล้ว. รายละเอียด: {e}', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการเพิ่มอะไหล่: {e}', 'danger')
                    conn.rollback()
                active_tab = 'spare_part'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user)

    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions, all_spare_part_categories=all_spare_part_categories, current_user=current_user, scanned_barcode_for_add=scanned_barcode_for_add)

@bp.route('/edit_tire/<int:tire_id>', methods=('GET', 'POST'))
@login_required
def edit_tire(tire_id):
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลยาง', 'danger')
        return redirect(url_for('stock.index'))
        
    conn = get_db()
    tire = database.get_tire(conn, tire_id)
    current_year = get_bkk_time().year

    if tire is None:
        flash('ไม่พบยางที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index', tab='tires'))

    all_promotions = get_all_promotions_cached()
    tire_barcodes = database.get_barcodes_for_tire(conn, tire_id)
    
    # NEW: ดึงประวัติการเปลี่ยนแปลงราคาทุน
    cost_history = database.get_tire_cost_history(conn, tire_id)

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
            conn.rollback()
        else:
            try:
                price_per_item = float(price_per_item)

                # Adjusted variable name for clarity
                new_cost_sc_float = float(cost_sc) if cost_sc and cost_sc.strip() else None
                cost_dunlop = float(cost_dunlop) if cost_dunlop and cost_dunlop.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if pd.notna(wholesale_price1) and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if pd.notna(wholesale_price2) and wholesale_price2.strip() else None
                
                year_of_manufacture = year_of_manufacture.strip() if year_of_manufacture and year_of_manufacture.strip() else None

                # --- START: ส่วนที่เพิ่มเข้ามาเพื่อบันทึกประวัติ ---
                old_cost_sc_float = tire.get('cost_sc')
                
                # ตรวจสอบว่ามีการเปลี่ยนแปลงค่า cost_sc จริงๆ
                if old_cost_sc_float != new_cost_sc_float:
                    database.add_tire_cost_history(
                        conn=conn,
                        tire_id=tire_id,
                        old_cost=old_cost_sc_float,
                        new_cost=new_cost_sc_float,
                        user_id=current_user.id,
                        notes="แก้ไขผ่านหน้าเว็บ"
                    )
                # --- END: ส่วนที่เพิ่มเข้ามา ---

                database.update_tire(conn, tire_id, brand, model, size, new_cost_sc_float, cost_dunlop, cost_online, 
                                     wholesale_price1, wholesale_price2, price_per_item, 
                                     promotion_id_db, 
                                     year_of_manufacture)
                conn.commit()
                flash('แก้ไขข้อมูลยางสำเร็จ!', 'success')
                cache.delete_memoized(get_cached_tire_brands)
                cache.delete_memoized(get_all_tires_list_cached)
                return redirect(url_for('stock.index', tab='tires'))
            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ยางยี่ห้อ {brand} รุ่น {model} เบอร์ {size} นี้มีอยู่ในระบบแล้วภายใต้ ID อื่น โปรดตรวจสอบ', 'warning')
                else:
                    conn.rollback()
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลยาง: {e}', 'danger')

    # NEW: ส่ง cost_history ไปที่ template
    return render_template('edit_tire.html', tire=tire, current_year=current_year, all_promotions=all_promotions, tire_barcodes=tire_barcodes, cost_history=cost_history, current_user=current_user)
    
@bp.route('/api/tire/<int:tire_id>/barcodes', methods=['GET', 'POST', 'DELETE']) # <--- เพิ่ม 'GET' เข้าไป
@login_required
def api_manage_tire_barcodes(tire_id):
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการจัดการ Barcode ID"}), 403

    conn = get_db()

    # ✅ --- ส่วนที่เพิ่มเข้ามาสำหรับรองรับ GET --- ✅
    if request.method == 'GET':
        try:
            barcodes = database.get_barcodes_for_tire(conn, tire_id)
            return jsonify({"success": True, "barcodes": barcodes})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการดึงข้อมูลบาร์โค้ด: {str(e)}"}), 500
    # --- จบส่วนที่เพิ่ม ---

    # --- ส่วนของ POST และ DELETE ยังคงเหมือนเดิม ---
    data = request.get_json()
    barcode_string = data.get('barcode_string', '').strip()

    if not barcode_string:
        conn.rollback()
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    try:
        if request.method == 'POST':
            # ... (โค้ด POST ของคุณเหมือนเดิม) ...
            existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_string)
            # ... (ที่เหลือเหมือนเดิม) ...
            database.add_tire_barcode(conn, tire_id, barcode_string, is_primary=False)
            conn.commit()
            return jsonify({"success": True, "message": "เพิ่ม Barcode สำเร็จ!"}), 201

        elif request.method == 'DELETE':
            # ... (โค้ด DELETE ของคุณเหมือนเดิม) ...
            database.delete_tire_barcode(conn, barcode_string)
            conn.commit()
            return jsonify({"success": True, "message": "ลบ Barcode สำเร็จ!"}), 200
            
    except Exception as e:
        conn.rollback()
        # ... (โค้ด exception handling เหมือนเดิม) ...
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการจัดการ Barcode ID: {str(e)}"}), 500

@bp.route('/delete_tire/<int:tire_id>', methods=('POST',))
@login_required
def delete_tire(tire_id):
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการลบยาง"}), 403
        
    conn = get_db()
    tire = database.get_tire(conn, tire_id)

    if tire is None:
        return jsonify({"success": False, "message": "ไม่พบยางที่ระบุ"}), 404
        
    if tire['quantity'] > 0:
        return jsonify({"success": False, "message": "ไม่สามารถลบยางได้เนื่องจากยังมีสต็อกเหลืออยู่"}), 400

    try:
        database.delete_tire(conn, tire_id)
        conn.commit()
        cache.delete_memoized(get_cached_tire_brands)
        cache.delete_memoized(get_all_tires_list_cached)
        return jsonify({"success": True, "message": "ลบยางสำเร็จ!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการลบ: {e}"}), 500

# --- Wheel Routes (Main item editing) (assuming these are already in your app.py) ---
@bp.route('/wheel_detail/<int:wheel_id>')
@login_required
def wheel_detail(wheel_id):
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)
    fitments = database.get_wheel_fitments(conn, wheel_id)
    current_year = get_bkk_time().year

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index', tab='wheels'))
    
    return render_template('wheel_detail.html', wheel=wheel, fitments=fitments, current_year=current_year, current_user=current_user)

@bp.route('/edit_wheel/<int:wheel_id>', methods=('GET', 'POST'))
@login_required
def edit_wheel(wheel_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลแม็ก', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)
    current_year = get_bkk_time().year

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index', tab='wheels'))

    wheel_barcodes = database.get_barcodes_for_wheel(conn, wheel_id)

    if request.method == 'POST':
        # ดึงค่าจากฟอร์มทั้งหมด
        brand = request.form['brand'].strip()
        model = request.form['model'].strip()
        diameter_str = request.form['diameter'].strip()
        pcd = request.form['pcd'].strip()
        width_str = request.form['width'].strip()
        et_str = request.form.get('et', '').strip()
        color_str = request.form.get('color', '').strip()
        cost_str = request.form.get('cost', '').strip()
        cost_online_str = request.form.get('cost_online', '').strip()
        wholesale_price1_str = request.form.get('wholesale_price1', '').strip()
        wholesale_price2_str = request.form.get('wholesale_price2', '').strip()
        retail_price_str = request.form['retail_price'].strip()

        image_file = request.files.get('image_file')
        current_quantity = wheel['quantity']
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = wheel['image_filename'] # Initialize with current image URL

        try:
            # --- Type conversions (move into the main try block) ---
            diameter = float(diameter_str)
            width = float(width_str)
            retail_price = float(retail_price_str)

            et = int(et_str) if et_str else None
            cost = float(cost_str) if cost_str else None
            cost_online = float(cost_online_str) if cost_online_str else None
            wholesale_price1 = float(wholesale_price1_str) if wholesale_price1_str else None
            wholesale_price2 = float(wholesale_price2_str) if wholesale_price2_str else None
            color = color_str

            if not brand or not model or not pcd or not diameter_str or not width_str or not retail_price_str:
                flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                conn.rollback()
                return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes, current_user=current_user)

            # --- Image handling logic (now within the main try block) ---
            if delete_existing_image and current_image_url:
                try:
                    if current_app.config['CLOUDINARY_AVAILABLE']:
                        if "res.cloudinary.com" in current_image_url:
                            public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                            if public_id_match:
                                public_id = public_id_match.group(1)
                                cloudinary.uploader.destroy(public_id)
                    else: # Local storage
                        if "/uploads/" in current_image_url:
                            old_filename = current_image_url.split('/')[-1]
                            old_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename) # Use current_app.config
                            if os.path.exists(old_filepath):
                                os.remove(old_filepath)
                    current_image_url = None # Set to None after successful deletion
                except Exception as e:
                    # Log the error but don't halt the request, just don't set image_url to None
                    print(f"Error deleting old image: {e}")
                    flash(f'เกิดข้อผิดพลาดในการลบรูปภาพเดิม: {e}', 'warning')
            
            if image_file and image_file.filename != '':
                if allowed_image_file(image_file.filename):
                    try:
                        if current_app.config['CLOUDINARY_AVAILABLE']:
                            upload_result = cloudinary.uploader.upload(image_file)
                            current_image_url = upload_result['secure_url'] # Update to new URL
                        else:
                            original_filename = secure_filename(image_file.filename)
                            file_extension = os.path.splitext(original_filename)[1]
                            unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                            
                            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename) # Use current_app.config
                            image_file.save(filepath)
                            current_image_url = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                    except Exception as e:
                        flash(f'เกิดข้อผิดผิดพลาดในการอัปโหลดรูปภาพใหม่: {e}', 'danger')
                        conn.rollback()
                        # Important: If image upload fails, you might want to rollback here too if it's considered part of the atomic update
                        # For now, let's assume if it fails here, the main update might still proceed without the image.
                        # If you want it atomic, put this in the main try-except.
                        raise # Re-raise to be caught by the outer try-except for rollback.
                else:
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes, current_user=current_user)

            # --- Database update (now safe within the main try block) ---
            database.update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, current_quantity, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, current_image_url)
            conn.commit()
            flash('แก้ไขข้อมูลแม็กสำเร็จ!', 'success')
            cache.delete_memoized(get_all_wheels_list_cached)
            cache.delete_memoized(get_cached_wheel_brands)
            return redirect(url_for('stock.wheel_detail', wheel_id=wheel_id))

        except ValueError as e:
            conn.rollback() # Ensure rollback on value errors
            flash(f'ข้อมูลตัวเลขไม่ถูกต้องในช่องขนาด, ET, ทุน, หรือราคา กรุณาตรวจสอบ: {e}', 'danger')
            return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes, current_user=current_user)
        except (psycopg2.errors.UniqueViolation, sqlite3.IntegrityError) as e: # Catch specific integrity errors first
            conn.rollback()
            flash(f'แม็กยี่ห้อ {brand} ลาย {model} ขอบ {diameter} รู {pcd} กว้าง {width} นี้มีอยู่ในระบบแล้วภายใต้ ID อื่น โปรดตรวจสอบ', 'warning')
            return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes, current_user=current_user)
        except Exception as e: # Catch any other unexpected errors
            conn.rollback() # Crucially, rollback for any other error
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลแม็ก: {e}', 'danger')
            # For debugging, log the full traceback:
            import traceback
            traceback.print_exc()
            return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes, current_user=current_user)

    return render_template('edit_wheel.html', wheel=wheel, current_year=current_year, wheel_barcodes=wheel_barcodes, current_user=current_user)

@bp.route('/api/wheel/<int:wheel_id>/barcodes', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_manage_wheel_barcodes(wheel_id):
    if not current_user.can_edit(): # Admin or Editor
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการจัดการ Barcode ID"}), 403

    conn = get_db()
    
    # --- ส่วนที่แก้ไข: จัดการ GET request ก่อน ---
    if request.method == 'GET':
        try:
            barcodes = database.get_barcodes_for_wheel(conn, wheel_id)
            return jsonify({"success": True, "barcodes": barcodes})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "message": str(e)}), 500
    
    # --- ส่วนของ POST และ DELETE จะทำงานเฉพาะเมื่อไม่ใช่ GET ---
    # ย้ายการดึงข้อมูล JSON มาไว้ตรงนี้
    data = request.get_json()
    if not data:
        conn.rollback()
        return jsonify({"success": False, "message": "ไม่พบข้อมูลที่ส่งมา"}), 400
        
    barcode_string = data.get('barcode_string', '').strip()
    if not barcode_string:
        conn.rollback()
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    try:
        if request.method == 'POST':
            existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_string)
            existing_wheel_id_by_barcode = database.get_wheel_id_by_barcode(conn, barcode_string)

            if existing_wheel_id_by_barcode:
                conn.rollback()
                if existing_wheel_id_by_barcode != wheel_id:
                    conn.rollback()
                    return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับแม็กอื่น (ID: {existing_wheel_id_by_barcode}) แล้ว"}), 409
                else:
                    return jsonify({"success": True, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับแม็กนี้อยู่แล้ว"}), 200
            
            if existing_tire_id_by_barcode:
                conn.rollback()
                return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับยาง (ID: {existing_tire_id_by_barcode}) แล้ว"}), 409
            
            database.add_wheel_barcode(conn, wheel_id, barcode_string, is_primary=False)
            conn.commit()
            return jsonify({"success": True, "message": "เพิ่ม Barcode ID สำเร็จ!"}), 201 # Use 201 for created

        elif request.method == 'DELETE':
            database.delete_wheel_barcode(conn, barcode_string)
            conn.commit()
            return jsonify({"success": True, "message": "ลบ Barcode ID สำเร็จ!"}), 200
            
    except Exception as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
             return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' มีอยู่ในระบบแล้ว"}), 409
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการจัดการ Barcode ID: {str(e)}"}), 500

@bp.route('/delete_wheel/<int:wheel_id>', methods=('POST',))
@login_required
def delete_wheel(wheel_id):
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการลบแม็ก"}), 403
        
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)

    if wheel is None:
        return jsonify({"success": False, "message": "ไม่พบแม็กที่ระบุ"}), 404
    
    if wheel['quantity'] > 0:
        return jsonify({"success": False, "message": "ไม่สามารถลบแม็กได้เนื่องจากยังมีสต็อกเหลืออยู่"}), 400

    try:
        database.delete_wheel(conn, wheel_id)
        conn.commit()
        cache.delete_memoized(get_all_wheels_list_cached)
        cache.delete_memoized(get_cached_wheel_brands)
        return jsonify({"success": True, "message": "ลบแม็กสำเร็จ!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการลบแม็ก: {e}"}), 500

@bp.route('/add_fitment/<int:wheel_id>', methods=('POST',))
@login_required
def add_fitment(wheel_id):
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการเพิ่มข้อมูล', 'danger')
        return redirect(url_for('stock.wheel_detail', wheel_id=wheel_id))
        
    conn = get_db()
    brand = request.form['brand'].strip()
    model = request.form['model'].strip()
    year_start = request.form['year_start'].strip()
    year_end = request.form.get('year_end', '').strip()

    if not brand or not model or not year_start:
        flash('กรุณากรอกข้อมูลให้ครบถ้วน', 'danger')
        conn.rollback()
    else:
        try:
            year_start = int(year_start)
            year_end = int(year_end) if year_end else None

            if year_end and year_end < year_start:
                conn.rollback()
                flash('ปีสิ้นสุดต้องไม่น้อยกว่าปีเริ่มต้น', 'danger')
            else:
                database.add_wheel_fitment(conn, wheel_id, brand, model, year_start, year_end)
                conn.commit()
                flash('เพิ่มข้อมูลการรองรับสำเร็จ!', 'success')
        except ValueError:
            conn.rollback()
            flash('ข้อมูลปีไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาดในการเพิ่มข้อมูลการรองรับ: {e}', 'danger')
    
    return redirect(url_for('stock.wheel_detail', wheel_id=wheel_id))

@bp.route('/delete_fitment/<int:fitment_id>/<int:wheel_id>', methods=('POST',))
@login_required
def delete_fitment(fitment_id, wheel_id):
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการลบข้อมูลการรองรับรถยนต์', 'danger')
        return redirect(url_for('stock.wheel_detail', wheel_id=wheel_id))
        
    conn = get_db()
    try:
        database.delete_wheel_fitment(conn, fitment_id)
        flash('ลบข้อมูลการรองรับสำเร็จ!', 'success')
        conn.commit()
    except Exception as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาดในการลบข้อมูลการรองรับ: {e}', 'danger')
    
    return redirect(url_for('stock.wheel_detail', wheel_id=wheel_id))

@bp.route('/spare_part_detail/<int:spare_part_id>')
@login_required
def spare_part_detail(spare_part_id):
    conn = get_db()
    spare_part = database.get_spare_part(conn, spare_part_id)

    if spare_part is None:
        flash('ไม่พบอะไหล่ที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index', tab='spare_parts'))

    # Filter data based on viewing permissions
    if not current_user.can_view_cost():
        spare_part['cost'] = None
        spare_part['cost_online'] = None
    if not current_user.can_view_wholesale_price_1():
        spare_part['wholesale_price1'] = None
    if not current_user.can_view_wholesale_price_2():
        spare_part['wholesale_price2'] = None
    if not current_user.can_view_retail_price():
        spare_part['retail_price'] = None


    return render_template('spare_part_detail.html', spare_part=spare_part, current_user=current_user)

@bp.route('/edit_spare_part/<int:spare_part_id>', methods=('GET', 'POST'))
@login_required
def edit_spare_part(spare_part_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลอะไหล่', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    spare_part = database.get_spare_part(conn, spare_part_id)
    all_spare_part_categories = get_cached_spare_part_categories_hierarchical()

    if spare_part is None:
        flash('ไม่พบอะไหล่ที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index', tab='spare_parts'))

    spare_part_barcodes = database.get_barcodes_for_spare_part(conn, spare_part_id)

    if request.method == 'POST':
        name = request.form['name'].strip()
        part_number = request.form.get('part_number', '').strip()
        brand = request.form.get('brand', '').strip().lower()
        description = request.form.get('description', '').strip()
        retail_price = request.form['retail_price']
        category_id = request.form.get('category_id')

        cost = request.form.get('cost')
        cost_online = request.form.get('cost_online')
        wholesale_price1 = request.form.get('wholesale_price1')
        wholesale_price2 = request.form.get('wholesale_price2')

        image_file = request.files.get('image_file')
        current_image_url = spare_part['image_filename']

        if not name or not retail_price:
            flash('กรุณากรอกข้อมูลอะไหล่ให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
            conn.rollback()
        else:
            if category_id == 'none' or not category_id:
                category_id_db = None
            else:
                category_id_db = int(category_id)

            # --- START: MODIFIED UPLOAD/DELETE LOGIC ---
            if image_file and image_file.filename != '':
                if allowed_image_file(image_file.filename):
                    try:
                        if current_app.config['CLOUDINARY_AVAILABLE']:
                            upload_result = cloudinary.uploader.upload(image_file)
                            new_image_url = upload_result['secure_url']

                            # Delete old image from Cloudinary
                            if current_image_url and "res.cloudinary.com" in current_image_url:
                                public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                                if public_id_match:
                                    public_id = public_id_match.group(1)
                                    try:
                                        cloudinary.uploader.destroy(public_id)
                                    except Exception as e:
                                        print(f"Error deleting old image from Cloudinary for spare part: {e}")
                        else:
                             # Use local storage
                            filename = secure_filename(image_file.filename)
                            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                            image_file.save(filepath)
                            new_image_url = url_for('stock.uploaded_file', filename=filename, _external=True)

                            # Delete old image from local storage
                            if current_image_url and "/uploads/" in current_image_url:
                                old_filename = current_image_url.split('/')[-1]
                                old_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                                if os.path.exists(old_filepath):
                                    os.remove(old_filepath)
                        
                        current_image_url = new_image_url

                    except Exception as e:
                        flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพ: {e}', 'danger')
                        conn.rollback()
                        return render_template('edit_spare_part.html', spare_part=spare_part, all_spare_part_categories=all_spare_part_categories, spare_part_barcodes=spare_part_barcodes, current_user=current_user)
                else:
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part.html', spare_part=spare_part, all_spare_part_categories=all_spare_part_categories, spare_part_barcodes=spare_part_barcodes, current_user=current_user)
            # --- END: MODIFIED UPLOAD/DELETE LOGIC ---

            try:
                retail_price = float(retail_price)
                cost = float(cost) if cost and cost.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None

                database.update_spare_part(conn, spare_part_id, name, part_number, brand, description,
                                           cost, retail_price, wholesale_price1, wholesale_price2, cost_online,
                                           current_image_url, category_id_db)
                conn.commit()
                flash('แก้ไขข้อมูลอะไหล่สำเร็จ!', 'success')
                cache.delete_memoized(get_all_spare_parts_cached)
                cache.delete_memoized(get_cached_spare_part_brands)
                return redirect(url_for('stock.spare_part_detail', spare_part_id=spare_part_id))
            except ValueError:
                conn.rollback()
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            except (sqlite3.IntegrityError, Exception) as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'เกิดข้อผิดพลาด: รหัสอะไหล่หรือชื่อซ้ำซ้อนในระบบ. รายละเอียด: {e}', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลอะไหล่: {e}', 'danger')
                    conn.rollback()

    # Ensure to pass updated spare_part_barcodes and current_user to the template on GET or error
    return render_template('edit_spare_part.html', spare_part=spare_part,
                           all_spare_part_categories=all_spare_part_categories,
                           spare_part_barcodes=spare_part_barcodes, current_user=current_user)

@bp.route('/delete_spare_part/<int:spare_part_id>', methods=('POST',))
@login_required
def delete_spare_part(spare_part_id):
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการลบอะไหล่"}), 403

    conn = get_db()
    spare_part = database.get_spare_part(conn, spare_part_id)

    if spare_part is None:
        return jsonify({"success": False, "message": "ไม่พบอะไหล่ที่ระบุ"}), 404

    if spare_part['quantity'] > 0:
        return jsonify({"success": False, "message": "ไม่สามารถลบอะไหล่ได้เนื่องจากยังมีสต็อกเหลืออยู่"}), 400

    try:
        database.delete_spare_part(conn, spare_part_id)
        conn.commit()
        cache.delete_memoized(get_all_spare_parts_cached)
        cache.delete_memoized(get_cached_spare_part_brands)
        return jsonify({"success": True, "message": "ลบอะไหล่สำเร็จ!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการลบ: {e}"}), 500

# --- API for managing Spare Part Barcodes ---
@bp.route('/api/spare_part/<int:spare_part_id>/barcodes', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_manage_spare_part_barcodes(spare_part_id):
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการจัดการ Barcode ID"}), 403

    conn = get_db()

    if request.method == 'GET':
        try:
            barcodes = database.get_barcodes_for_spare_part(conn, spare_part_id)
            return jsonify({"success": True, "barcodes": barcodes})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการดึงข้อมูลบาร์โค้ด: {str(e)}"}), 500

    data = request.get_json()
    barcode_string = data.get('barcode_string', '').strip()

    if not barcode_string:
        conn.rollback()
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    try:
        if request.method == 'POST':
            # ตรวจสอบว่า Barcode นี้ถูกใช้กับสินค้าอื่นอยู่แล้วหรือไม่ (ทั้งยาง, ล้อ, อะไหล่)
            existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_string)
            existing_wheel_id_by_barcode = database.get_wheel_id_by_barcode(conn, barcode_string)
            existing_spare_part_id_by_barcode = database.get_spare_part_id_by_barcode(conn, barcode_string)

            if existing_spare_part_id_by_barcode:
                conn.rollback()
                if existing_spare_part_id_by_barcode != spare_part_id:
                    return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับอะไหล่อื่น (ID: {existing_spare_part_id_by_barcode}) แล้ว"}), 409
                else:
                    return jsonify({"success": True, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับอะไหล่นี้อยู่แล้ว"}), 200

            if existing_tire_id_by_barcode:
                conn.rollback()
                return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับยาง (ID: {existing_tire_id_by_barcode}) แล้ว"}), 409

            if existing_wheel_id_by_barcode:
                conn.rollback()
                return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' ถูกเชื่อมโยงกับล้อแม็ก (ID: {existing_wheel_id_by_barcode}) แล้ว"}), 409

            database.add_spare_part_barcode(conn, spare_part_id, barcode_string, is_primary=False)
            conn.commit()
            return jsonify({"success": True, "message": "เพิ่ม Barcode สำเร็จ!"}), 201

        elif request.method == 'DELETE':
            database.delete_spare_part_barcode(conn, barcode_string)
            conn.commit()
            return jsonify({"success": True, "message": "ลบ Barcode สำเร็จ!"}), 200

    except Exception as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
             return jsonify({"success": False, "message": f"บาร์โค้ด '{barcode_string}' มีอยู่ในระบบแล้ว"}), 409
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการจัดการ Barcode ID: {str(e)}"}), 500

@cache.memoize(timeout=600) # Cache 10 นาที เพราะข้อมูลเปลี่ยนเมื่อมีการเพิ่ม/ลบสินค้า
def get_all_tires_list_cached():
    print("--- CACHE MISS (All Tires List) --- Fetching complete tire list from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_tires(conn, include_deleted=False)

@cache.memoize(timeout=600)
def get_all_wheels_list_cached():
    print("--- CACHE MISS (All Wheels List) --- Fetching complete wheel list from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_wheels(conn, include_deleted=False)

@cache.memoize(timeout=600)
def get_all_spare_parts_list_cached():
    print("--- CACHE MISS (All Spare Parts List) --- Fetching complete spare part list from DB")
    with current_app.app_context():
        conn = get_db()
        return database.get_all_spare_parts(conn)


# --- Stock Movement Routes (Movement editing) (assuming these are already in your app.py) ---
@bp.route('/stock_movement', methods=('GET', 'POST'))
@login_required
def stock_movement():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการจัดการการเคลื่อนไหวสต็อก', 'danger')
        return redirect(url_for('stock.index'))
    conn = get_db()

    tires = get_all_tires_list_cached()
    wheels = get_all_wheels_list_cached()
    spare_parts = get_all_spare_parts_list_cached() # NEW: Get all spare parts for dropdown

    sales_channels = get_all_sales_channels_cached()
    online_platforms = get_all_online_platforms_cached()
    wholesale_customers = get_all_wholesale_customers_cached()

    active_tab = request.args.get('tab', 'tire_movements')

    # --- สำหรับ Tire Movements History (โค้ดเดิม) ---
    tire_movements_query = """
        SELECT tm.id, tm.timestamp, tm.type, tm.quantity_change, tm.remaining_quantity, tm.image_filename, tm.notes,
               t.id AS tire_main_id, t.brand, t.model, t.size,
               u.username AS user_username,
               sc.name AS channel_name,
               op.name AS online_platform_name,
               wc.name AS wholesale_customer_name,
               tm.return_customer_type, tm.channel_id, tm.online_platform_id, tm.wholesale_customer_id
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        LEFT JOIN users u ON tm.user_id = u.id
        LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
        LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
        ORDER BY tm.timestamp DESC LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor_tire = conn.cursor()
        cursor_tire.execute(tire_movements_query)
        tire_movements_history_raw = cursor_tire.fetchall()
        cursor_tire.close()
    else:
        tire_movements_history_raw = conn.execute(tire_movements_query).fetchall()

    processed_tire_movements_history = []
    for movement in tire_movements_history_raw:
        movement_data = dict(movement)
        movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp']) # ใช้ database.convert_to_bkk_time
        processed_tire_movements_history.append(movement_data)
    tire_movements_history = processed_tire_movements_history


    # --- สำหรับ Wheel Movements History (โค้ดเดิม) ---
    wheel_movements_query = """
        SELECT wm.id, wm.timestamp, wm.type, wm.quantity_change, wm.remaining_quantity, wm.image_filename, wm.notes,
               w.id AS wheel_main_id, w.brand, w.model, w.diameter,
               u.username AS user_username,
               sc.name AS channel_name,
               op.name AS online_platform_name,
               wc.name AS wholesale_customer_name,
               wm.return_customer_type, wm.channel_id, wm.online_platform_id, wm.wholesale_customer_id
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        LEFT JOIN users u ON wm.user_id = u.id
        LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
        LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
        ORDER BY wm.timestamp DESC LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor_wheel = conn.cursor()
        cursor_wheel.execute(wheel_movements_query)
        wheel_movements_history_raw = cursor_wheel.fetchall()
        cursor_wheel.close()
    else:
        wheel_movements_history_raw = conn.execute(wheel_movements_query).fetchall()

    processed_wheel_movements_history = []
    for movement in wheel_movements_history_raw:
        movement_data = dict(movement)
        movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp']) # ใช้ database.convert_to_bkk_time
        processed_wheel_movements_history.append(movement_data)
    wheel_movements_history = processed_wheel_movements_history

    # NEW: สำหรับ Spare Part Movements History
    spare_part_movements_query = """
        SELECT spm.id, spm.timestamp, spm.type, spm.quantity_change, spm.remaining_quantity, spm.image_filename, spm.notes,
               sp.id AS spare_part_main_id, sp.name AS spare_part_name, sp.part_number, sp.brand AS spare_part_brand,
               u.username AS user_username,
               sc.name AS channel_name,
               op.name AS online_platform_name,
               wc.name AS wholesale_customer_name,
               spm.return_customer_type, spm.channel_id, spm.online_platform_id, spm.wholesale_customer_id
        FROM spare_part_movements spm
        JOIN spare_parts sp ON spm.spare_part_id = sp.id
        LEFT JOIN users u ON spm.user_id = u.id
        LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
        LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
        ORDER BY spm.timestamp DESC LIMIT 50
    """
    if "psycopg2" in str(type(conn)):
        cursor_spare_part = conn.cursor()
        cursor_spare_part.execute(spare_part_movements_query)
        spare_part_movements_history_raw = cursor_spare_part.fetchall()
        cursor_spare_part.close()
    else:
        spare_part_movements_history_raw = conn.execute(spare_part_movements_query).fetchall()

    processed_spare_part_movements_history = []
    for movement in spare_part_movements_history_raw:
        movement_data = dict(movement)
        movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])
        processed_spare_part_movements_history.append(movement_data)
    spare_part_movements_history = processed_spare_part_movements_history


    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        active_tab_on_error = 'tire_movements' # Default to tire tab on error

        if submit_type == 'tire_movement':
            item_id_key = 'tire_id'
            quantity_form_key = 'quantity'
            active_tab_on_error = 'tire_movements'
        elif submit_type == 'wheel_movement':
            item_id_key = 'wheel_id'
            quantity_form_key = 'quantity'
            active_tab_on_error = 'wheel_movements'
        elif submit_type == 'spare_part_movement': # NEW
            item_id_key = 'spare_part_id'
            quantity_form_key = 'quantity'
            active_tab_on_error = 'spare_part_movements'
        else:
            flash('ประเภทการส่งฟอร์มไม่ถูกต้อง', 'danger')
            conn.rollback()
            return redirect(url_for('stock.stock_movement'))

        if quantity_form_key not in request.form or not request.form[quantity_form_key].strip():
            flash('กรุณากรอกจำนวนที่เปลี่ยนแปลงให้ถูกต้อง', 'danger')
            conn.rollback()
            return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

        try:
            item_id = request.form[item_id_key]
            move_type = request.form['type']
            quantity_change = int(request.form[quantity_form_key])
            notes = request.form.get('notes', '').strip()
            bill_image_file = request.files.get('bill_image')

            bill_image_url_to_db = None

            # --- START: MODIFIED UPLOAD LOGIC ---
            if bill_image_file and bill_image_file.filename != '':
                if allowed_image_file(bill_image_file.filename):
                    try:
                        if current_app.config['CLOUDINARY_AVAILABLE']:
                            upload_result = cloudinary.uploader.upload(bill_image_file)
                            bill_image_url_to_db = upload_result['secure_url']
                        else:
                            filename = secure_filename(bill_image_file.filename)
                            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                            bill_image_file.save(filepath)
                            bill_image_url_to_db = url_for('stock.uploaded_file', filename=filename, _external=True)
                    except Exception as e:
                        flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิล: {e}', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                else:
                    flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
            # --- END: MODIFIED UPLOAD LOGIC ---

            if quantity_change <= 0:
                flash('จำนวนที่เปลี่ยนแปลงต้องมากกว่า 0', 'danger')
                conn.rollback()
                return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

            current_user_id = current_user.id if current_user.is_authenticated else None

            # MODIFIED: Get channel-specific data from form
            channel_id_str = request.form.get('channel_id')
            online_platform_id_str = request.form.get('online_platform_id') # สำหรับ OUT ช่องทาง 'ออนไลน์'
            wholesale_customer_id_str = request.form.get('wholesale_customer_id') # สำหรับ OUT ช่องทาง 'ค้าส่ง'
            return_customer_type = request.form.get('return_customer_type')

            # NEW: รับค่าสำหรับ 'ชื่อร้านยางที่คืน'
            return_wholesale_customer_id_str = request.form.get('return_wholesale_customer_id')
            # NEW: รับค่าสำหรับ 'แพลตฟอร์มออนไลน์ที่คืน'
            return_online_platform_id_str = request.form.get('return_online_platform_id')

            final_channel_id = int(channel_id_str) if channel_id_str else None

            # NEW: กำหนดค่าเริ่มต้นของ final_online_platform_id และ final_wholesale_customer_id เป็น None ก่อน
            final_online_platform_id = None
            final_wholesale_customer_id = None

            # Logic validation: Ensure correct channel is selected for specific types
            channel_name = database.get_sales_channel_name(conn, final_channel_id)

            if move_type == 'IN':
                if channel_name != 'ซื้อเข้า':
                    flash('สำหรับประเภท "รับเข้า" ช่องทางการเคลื่อนไหวต้องเป็น "ซื้อเข้า" เท่านั้น', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                # final_online_platform_id และ final_wholesale_customer_id จะเป็น None อยู่แล้ว
                return_customer_type = None

            elif move_type == 'RETURN':
                if channel_name != 'รับคืน':
                    flash('สำหรับประเภท "รับคืน/ตีคืน" ช่องทางการเคลื่อนไหวต้องเป็น "รับคืน" เทinั้น', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

                if not return_customer_type:
                    flash('กรุณาระบุ "คืนจาก" สำหรับประเภท "รับคืน/ตีคืน"', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

                # Logic for "ออนไลน์" return
                if return_customer_type == 'ออนไลน์':
                    if not return_online_platform_id_str: # ใช้ return_online_platform_id_str ที่รับมาใหม่
                        flash('กรุณาระบุ "แพลตฟอร์มออนไลน์ที่คืน" สำหรับการคืนจาก "ออนไลน์"', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    try:
                        final_online_platform_id = int(return_online_platform_id_str)
                    except ValueError:
                        flash('ข้อมูลแพลตฟอร์มออนไลน์ที่คืนไม่ถูกต้อง', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                else:
                    final_online_platform_id = None # Clear if not online return

                # Logic for "หน้าร้านร้านยาง" return (ใช้ return_wholesale_customer_id_str ที่รับมาใหม่)
                if return_customer_type == 'หน้าร้านร้านยาง':
                    if not return_wholesale_customer_id_str: # ตรวจสอบว่ามีค่าส่งมาหรือไม่
                        flash('กรุณาระบุ "ชื่อร้านยาง" สำหรับการคืนจาก "หน้าร้าน (ร้านยาง)"', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    try:
                        final_wholesale_customer_id = int(return_wholesale_customer_id_str)
                    except ValueError:
                        flash('ข้อมูลชื่อร้านยางไม่ถูกต้อง', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                # หากเป็น 'หน้าร้านลูกค้าทั่วไป' ก็ไม่จำเป็นต้องมี final_wholesale_customer_id
                # final_wholesale_customer_id จะถูกเก็บเป็น None ตั้งแต่ต้นอยู่แล้ว ถ้าไม่เข้าเงื่อนไขนี้

            elif move_type == 'OUT':
                if channel_name == 'ซื้อเข้า' or channel_name == 'รับคืน':
                    flash(f'สำหรับประเภท "จ่ายออก" ช่องทางการเคลื่อนไหวไม่สามารถเป็น "{channel_name}" ได้', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

                if channel_name == 'ออนไลน์':
                    if not online_platform_id_str: # ใช้ online_platform_id_str เดิมสำหรับ OUT ช่องทางออนไลน์
                        flash('กรุณาระบุ "แพลตฟอร์มออนไลน์" สำหรับช่องทาง "ออนไลน์"', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    try:
                        final_online_platform_id = int(online_platform_id_str)
                    except ValueError:
                        flash('ข้อมูลแพลตฟอร์มออนไลน์ไม่ถูกต้อง', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                else:
                    final_online_platform_id = None # Clear if not online

                if channel_name == 'ค้าส่ง':
                    if not wholesale_customer_id_str: # ใช้ wholesale_customer_id_str เดิมสำหรับ OUT ค้าส่ง
                        flash('กรุณาระบุ "ชื่อลูกค้าค้าส่ง" สำหรับช่องทาง "ค้าส่ง"', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    try:
                        final_wholesale_customer_id = int(wholesale_customer_id_str)
                    except ValueError:
                        flash('ข้อมูลชื่อลูกค้าค้าส่งไม่ถูกต้อง', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                else:
                    final_wholesale_customer_id = None # Make sure this is None for other OUT channels

                return_customer_type = None # Clear if not applicable

            # --- Process Tire Movement ---
            if submit_type == 'tire_movement':
                tire_id = int(item_id)
                current_tire = database.get_tire(conn, tire_id)
                if current_tire is None:
                    flash('ไม่พบยางที่ระบุ', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

                new_quantity = current_tire['quantity']
                if move_type == 'IN' or move_type == 'RETURN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกยางไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} เส้น.', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change

                database.update_tire_quantity(conn, tire_id, new_quantity)
                database.add_tire_movement(conn, tire_id, move_type, quantity_change, new_quantity, notes,
                                            bill_image_url_to_db, user_id=current_user_id,
                                            channel_id=final_channel_id,
                                            online_platform_id=final_online_platform_id,
                                            wholesale_customer_id=final_wholesale_customer_id,
                                            return_customer_type=return_customer_type)
                flash(f'บันทึกการเคลื่อนไหวสต็อกยางสำเร็จ! คงเหลือ: {new_quantity} เส้น', 'success')
                cache.delete_memoized(get_all_tires_list_cached)

                tire_info = database.get_tire(conn, tire_id)
                message = (
                    f"สต็อกยาง [{move_type}]: {tire_info['brand'].title()} {tire_info['model'].title()} ({tire_info['size']}) "
                    f"จำนวน {quantity_change} เส้น (คงเหลือ: {new_quantity}) "
                    f"โดย {current_user.username}"
                    )
                database.add_notification(conn, message, current_user.id)
                conn.commit()
                cache.delete_memoized(get_cached_unread_notification_count)
                return redirect(url_for('stock.stock_movement', tab='tire_movements'))

            # --- Process Wheel Movement ---
            elif submit_type == 'wheel_movement':
                wheel_id = int(item_id)
                current_wheel = database.get_wheel(conn, wheel_id)
                if current_wheel is None:
                    flash('ไม่พบแม็กที่ระบุ', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

                new_quantity = current_wheel['quantity']
                if move_type == 'IN' or move_type == 'RETURN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกแม็กไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} วง.', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change

                database.update_wheel_quantity(conn, wheel_id, new_quantity)
                database.add_wheel_movement(conn, wheel_id, move_type, quantity_change, new_quantity, notes,
                                             bill_image_url_to_db, user_id=current_user_id,
                                             channel_id=final_channel_id,
                                             online_platform_id=final_online_platform_id,
                                             wholesale_customer_id=final_wholesale_customer_id,
                                             return_customer_type=return_customer_type)
                flash(f'บันทึกการเคลื่อนไหวสต็อกแม็กสำเร็จ! คงเหลือ: {new_quantity} วง', 'success')
                cache.delete_memoized(get_all_wheels_list_cached)

                wheel_info = database.get_wheel(conn, wheel_id)
                message = (
                        f"สต็อกแม็ก [{move_type}]: {wheel_info['brand'].title()} {wheel_info['model'].title()} "
                        f"จำนวน {quantity_change} วง (คงเหลือ: {new_quantity}) "
                        f"โดย {current_user.username}"
                    )
                database.add_notification(conn, message, current_user.id)
                conn.commit()
                cache.delete_memoized(get_cached_unread_notification_count)
                return redirect(url_for('stock.stock_movement', tab='wheel_movements'))

            # NEW: Process Spare Part Movement
            elif submit_type == 'spare_part_movement':
                spare_part_id = int(item_id)
                current_spare_part = database.get_spare_part(conn, spare_part_id)
                if current_spare_part is None:
                    flash('ไม่พบอะไหล่ที่ระบุ', 'danger')
                    conn.rollback()
                    return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

                new_quantity = current_spare_part['quantity']
                if move_type == 'IN' or move_type == 'RETURN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกอะไหล่ไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} ชิ้น.', 'danger')
                        conn.rollback()
                        return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change

                database.update_spare_part_quantity(conn, spare_part_id, new_quantity)
                database.add_spare_part_movement(conn, spare_part_id, move_type, quantity_change, new_quantity, notes,
                                                  bill_image_url_to_db, user_id=current_user_id,
                                                  channel_id=final_channel_id,
                                                  online_platform_id=final_online_platform_id,
                                                  wholesale_customer_id=final_wholesale_customer_id,
                                                  return_customer_type=return_customer_type)
                flash(f'บันทึกการเคลื่อนไหวสต็อกอะไหล่สำเร็จ! คงเหลือ: {new_quantity} ชิ้น', 'success')

                spare_part_info = database.get_spare_part(conn, spare_part_id)
                message = (
                    f"สต็อกอะไหล่ [{move_type}]: {spare_part_info['name']} ({spare_part_info.get('brand', 'ไม่ระบุยี่ห้อ')}) "
                    f"จำนวน {quantity_change} ชิ้น (คงเหลือ: {new_quantity}) "
                    f"โดย {current_user.username}"
                )
                database.add_notification(conn, message, current_user.id)
                conn.commit()
                cache.delete_memoized(get_all_spare_parts_cached)
                cache.delete_memoized(get_all_spare_parts_list_cached)
                cache.delete_memoized(get_cached_unread_notification_count)
                return redirect(url_for('stock.stock_movement', tab='spare_part_movements'))


        except ValueError:
            conn.rollback()
            flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            conn.rollback()
            return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการบันทึกการเคลื่อนไหวสต็อก: {e}', 'danger')
            conn.rollback()
            return redirect(url_for('stock.stock_movement', tab=active_tab_on_error))

    return render_template('stock_movement.html',
                           tires=tires,
                           wheels=wheels,
                           spare_parts=spare_parts, # NEW
                           active_tab=active_tab,
                           tire_movements=tire_movements_history,
                           wheel_movements=wheel_movements_history,
                           spare_part_movements=spare_part_movements_history, # NEW
                           sales_channels=sales_channels,
                           online_platforms=online_platforms,
                           wholesale_customers=wholesale_customers,
                           current_user=current_user)

@bp.route('/edit_tire_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_tire_movement(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกยาง', 'danger')
        return redirect(url_for('stock.daily_stock_report'))

    conn = get_db()
    movement = database.get_tire_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.daily_stock_report'))

    movement_data = dict(movement)
    movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])

    sales_channels = database.get_all_sales_channels(conn)
    online_platforms = database.get_all_online_platforms(conn)
    wholesale_customers = database.get_all_wholesale_customers(conn)

    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        new_type = request.form['type']
        new_quantity_change = int(request.form['quantity_change'])
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement_data['image_filename']
        bill_image_url_to_db = current_image_url

        # --- START: MODIFIED UPLOAD/DELETE LOGIC ---
        if delete_existing_image:
            if current_app.config['CLOUDINARY_AVAILABLE']:
                if current_image_url and "res.cloudinary.com" in current_image_url:
                    public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                    if public_id_match:
                        public_id = public_id_match.group(1)
                        try:
                            cloudinary.uploader.destroy(public_id)
                        except Exception as e:
                            print(f"Error deleting old tire movement image from Cloudinary: {e}")
                            flash(f'เกิดข้อผิดพลาดในการลบรูปภาพบิลเดิม: {e}', 'warning')
                            conn.rollback()
            else:
                if current_image_url and "/uploads/" in current_image_url:
                    old_filename = current_image_url.split('/')[-1]
                    old_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
            bill_image_url_to_db = None

        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    if current_app.config['CLOUDINARY_AVAILABLE']:
                        upload_result = cloudinary.uploader.upload(bill_image_file)
                        new_image_url = upload_result['secure_url']
                    else:
                        # Use local storage
                        original_filename = secure_filename(bill_image_file.filename)
                        file_extension = os.path.splitext(original_filename)[1]
                        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                        
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                        bill_image_file.save(filepath)
                        new_image_url = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                    bill_image_url_to_db = new_image_url
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิล: {e}', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
        # --- END: MODIFIED UPLOAD/DELETE LOGIC ---

        # MODIFIED: Get channel-specific data from form
        new_channel_id_str = request.form.get('channel_id')
        new_online_platform_id_str = request.form.get('online_platform_id') # สำหรับ OUT ช่องทาง 'ออนไลน์'
        new_wholesale_customer_id_str = request.form.get('wholesale_customer_id') # สำหรับ OUT ช่องทาง 'ค้าส่ง'
        new_return_customer_type = request.form.get('return_customer_type')
        # NEW: รับค่าสำหรับ 'ชื่อร้านยางที่คืน'
        new_return_wholesale_customer_id_str = request.form.get('return_wholesale_customer_id') 
        # NEW: รับค่าสำหรับ 'แพลตฟอร์มออนไลน์ที่คืน'
        new_return_online_platform_id_str = request.form.get('return_online_platform_id') 
        
        final_new_channel_id = int(new_channel_id_str) if new_channel_id_str else None
        
        # NEW: กำหนดค่าเริ่มต้นของ final_new_online_platform_id และ final_new_wholesale_customer_id เป็น None ก่อน
        final_new_online_platform_id = None 
        final_new_wholesale_customer_id = None 

        # Logic validation for update: Similar to add, but on existing movement
        channel_name = database.get_sales_channel_name(conn, final_new_channel_id)
        if new_type == 'IN':
            if channel_name != 'ซื้อเข้า':
                flash('สำหรับประเภท "รับเข้า" ช่องทางการเคลื่อนไหวต้องเป็น "ซื้อเข้า" เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            # final_new_online_platform_id และ final_new_wholesale_customer_id จะเป็น None อยู่แล้ว
            new_return_customer_type = None
        elif new_type == 'RETURN':
            if channel_name != 'รับคืน':
                flash('สำหรับประเภท "รับคืน/ตีคืน" ช่องทางการเคลื่อนไหวต้องเป็น "รับคืน" เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            if not new_return_customer_type:
                flash('กรุณาระบุ "คืนจาก" สำหรับประเภท "รับคืน/ตีคืน"', 'danger')
                conn.rollback()
                return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            
            # Logic for "ออนไลน์" return
            if new_return_customer_type == 'ออนไลน์':
                if not new_return_online_platform_id_str: # ใช้ new_return_online_platform_id_str ที่รับมาใหม่
                    flash('กรุณาระบุ "แพลตฟอร์มออนไลน์ที่คืน" สำหรับการคืนจาก "ออนไลน์"', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_online_platform_id = int(new_return_online_platform_id_str)
                except ValueError:
                    flash('ข้อมูลแพลตฟอร์มออนไลน์ที่คืนไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_online_platform_id = None # Clear if not online return

            # Logic for "หน้าร้านร้านยาง" return (ใช้ new_return_wholesale_customer_id_str ที่รับมาใหม่)
            if new_return_customer_type == 'หน้าร้านร้านยาง':
                if not new_return_wholesale_customer_id_str: # ตรวจสอบว่ามีค่าส่งมาหรือไม่
                    flash('กรุณาระบุ "ชื่อร้านยาง" สำหรับการคืนจาก "หน้าร้าน (ร้านยาง)"', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_wholesale_customer_id = int(new_return_wholesale_customer_id_str)
                except ValueError:
                    flash('ข้อมูลชื่อร้านยางไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            # หากเป็น 'หน้าร้านลูกค้าทั่วไป' ก็ไม่จำเป็นต้องมี final_new_wholesale_customer_id
            # final_new_wholesale_customer_id จะถูกเก็บเป็น None ตั้งแต่ต้นอยู่แล้ว ถ้าไม่เข้าเงื่อนไขนี้

        elif new_type == 'OUT':
            if channel_name == 'ซื้อเข้า' or channel_name == 'รับคืน':
                flash(f'สำหรับประเภท "จ่ายออก" ช่องทางการเคลื่อนไหวไม่สามารถเป็น "{channel_name}" ได้', 'danger')
                conn.rollback()
                return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            if channel_name == 'ออนไลน์':
                if not new_online_platform_id_str: # ใช้ new_online_platform_id_str เดิมสำหรับ OUT ช่องทางออนไลน์
                    flash('กรุณาระบุ "แพลตฟอร์มออนไลน์" สำหรับช่องทาง "ออนไลน์"', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_online_platform_id = int(new_online_platform_id_str)
                except ValueError:
                    flash('ข้อมูลแพลตฟอร์มออนไลน์ไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_online_platform_id = None # Clear if not online
            
            if channel_name == 'ค้าส่ง':
                if not new_wholesale_customer_id_str: # ใช้ new_wholesale_customer_id_str เดิมสำหรับ OUT ค้าส่ง
                    flash('กรุณาระบุ "ชื่อลูกค้าค้าส่ง" สำหรับช่องทาง "ค้าส่ง"', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_wholesale_customer_id = int(new_wholesale_customer_id_str)
                except ValueError:
                    flash('ข้อมูลชื่อลูกค้าค้าส่งไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_tire_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_wholesale_customer_id = None # Make sure this is None for other OUT channels
            
            new_return_customer_type = None

        try:
            old_type = movement_data['type']
            old_quantity_change = movement_data['quantity_change']
            database.update_tire_movement(conn, movement_id, new_notes, bill_image_url_to_db, 
                                            new_type, new_quantity_change,
                                            final_new_channel_id, final_new_online_platform_id, 
                                            final_new_wholesale_customer_id, new_return_customer_type)
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกยางสำเร็จ!', 'success')

            tire_info = f"{movement_data['brand'].title()} {movement_data['model'].title()} ({movement_data['size']})"
            message = (
                f"แก้ไขสต็อกยาง: {tire_info} "
                f"จาก [{old_type}] {old_quantity_change} เส้น เป็น [{new_type}] {new_quantity_change} เส้น "
                f"โดย {current_user.username}"
            )
            database.add_notification(conn, message, current_user.id)
            conn.commit()
            cache.delete_memoized(get_cached_unread_notification_count)
            cache.delete_memoized(get_all_tires_list_cached)
            return redirect(url_for('stock.daily_stock_report'))
        except ValueError as e:
            flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            conn.rollback()
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')
            conn.rollback()

    return render_template('edit_tire_movement.html', 
                           movement=movement_data, 
                           current_user=current_user,
                           sales_channels=sales_channels,
                           online_platforms=online_platforms,
                           wholesale_customers=wholesale_customers)

@bp.route('/edit_wheel_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_wheel_movement(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกแม็ก', 'danger')
        return redirect(url_for('stock.daily_stock_report'))

    conn = get_db()
    movement = database.get_wheel_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.daily_stock_report'))

    movement_data = dict(movement)
    movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])

    sales_channels = database.get_all_sales_channels(conn)
    online_platforms = database.get_all_online_platforms(conn)
    wholesale_customers = database.get_all_wholesale_customers(conn)

    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        new_type = request.form['type']
        new_quantity_change = int(request.form['quantity_change'])
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement_data['image_filename']
        bill_image_url_to_db = current_image_url

        # --- START: MODIFIED UPLOAD/DELETE LOGIC ---
        if delete_existing_image:
            if current_app.config['CLOUDINARY_AVAILABLE']:
                if current_image_url and "res.cloudinary.com" in current_image_url:
                    public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                    if public_id_match:
                        public_id = public_id_match.group(1)
                        try:
                            cloudinary.uploader.destroy(public_id)
                        except Exception as e:
                            print(f"Error deleting old wheel movement image from Cloudinary: {e}")
                            flash(f'เกิดข้อผิดพลาดในการลบรูปภาพบิลเดิม: {e}', 'warning')
                            conn.rollback()
            else:
                if current_image_url and "/uploads/" in current_image_url:
                    old_filename = current_image_url.split('/')[-1]
                    old_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
            bill_image_url_to_db = None

        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    if current_app.config['CLOUDINARY_AVAILABLE']:
                        upload_result = cloudinary.uploader.upload(bill_image_file)
                        new_image_url = upload_result['secure_url']
                    else:
                        # Use local storage
                        original_filename = secure_filename(bill_image_file.filename)
                        file_extension = os.path.splitext(original_filename)[1]
                        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                        
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                        bill_image_file.save(filepath)
                        new_image_url = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                    bill_image_url_to_db = new_image_url
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิล: {e}', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
        # --- END: MODIFIED UPLOAD/DELETE LOGIC ---

        # MODIFIED: Get channel-specific data from form
        new_channel_id_str = request.form.get('channel_id')
        new_online_platform_id_str = request.form.get('online_platform_id') # สำหรับ OUT ช่องทาง 'ออนไลน์'
        new_wholesale_customer_id_str = request.form.get('wholesale_customer_id') # สำหรับ OUT ช่องทาง 'ค้าส่ง'
        new_return_customer_type = request.form.get('return_customer_type')
        # NEW: รับค่าสำหรับ 'ชื่อร้านยางที่คืน'
        new_return_wholesale_customer_id_str = request.form.get('return_wholesale_customer_id') 
        # NEW: รับค่าสำหรับ 'แพลตฟอร์มออนไลน์ที่คืน'
        new_return_online_platform_id_str = request.form.get('return_online_platform_id') 

        final_new_channel_id = int(new_channel_id_str) if new_channel_id_str else None
        
        # NEW: กำหนดค่าเริ่มต้นของ final_new_online_platform_id และ final_new_wholesale_customer_id เป็น None ก่อน
        final_new_online_platform_id = None 
        final_new_wholesale_customer_id = None 

        # Logic validation for update: Similar to add, but on existing movement
        channel_name = database.get_sales_channel_name(conn, final_new_channel_id)
        if new_type == 'IN':
            if channel_name != 'ซื้อเข้า':
                flash('สำหรับประเภท "รับเข้า" ช่องทางการเคลื่อนไหวต้องเป็น "ซื้อเข้า" เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            final_new_online_platform_id = None
            final_new_wholesale_customer_id = None
            new_return_customer_type = None
        elif new_type == 'RETURN':
            if channel_name != 'รับคืน':
                flash('สำหรับประเภท "รับคืน/ตีคืน" ช่องทางการเคลื่อนไหวต้องเป็น "รับคืน" เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            if not new_return_customer_type:
                flash('กรุณาระบุ "คืนจาก" สำหรับประเภท "รับคืน/ตีคืน"', 'danger')
                conn.rollback()
                return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            
            # Logic for "ออนไลน์" return
            if new_return_customer_type == 'ออนไลน์':
                if not new_return_online_platform_id_str: # ใช้ new_return_online_platform_id_str ที่รับมาใหม่
                    flash('กรุณาระบุ "แพลตฟอร์มออนไลน์ที่คืน" สำหรับการคืนจาก "ออนไลน์"', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_online_platform_id = int(new_return_online_platform_id_str)
                except ValueError:
                    flash('ข้อมูลแพลตฟอร์มออนไลน์ที่คืนไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_online_platform_id = None # Clear if not online return

            # Logic for "หน้าร้านร้านยาง" return (ใช้ new_return_wholesale_customer_id_str ที่รับมาใหม่)
            if new_return_customer_type == 'หน้าร้านร้านยาง':
                if not new_return_wholesale_customer_id_str: # ตรวจสอบว่ามีค่าส่งมาหรือไม่
                    flash('กรุณาระบุ "ชื่อร้านยาง" สำหรับการคืนจาก "หน้าร้าน (ร้านยาง)"', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_wholesale_customer_id = int(new_return_wholesale_customer_id_str)
                except ValueError:
                    flash('ข้อมูลชื่อร้านยางไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            # หากเป็น 'หน้าร้านลูกค้าทั่วไป' ก็ไม่จำเป็นต้องมี final_new_wholesale_customer_id
            # final_new_wholesale_customer_id จะถูกเก็บเป็น None ตั้งแต่ต้นอยู่แล้ว ถ้าไม่เข้าเงื่อนไขนี้

        elif new_type == 'OUT':
            if channel_name == 'ซื้อเข้า' or channel_name == 'รับคืน':
                flash(f'สำหรับประเภท "จ่ายออก" ช่องทางการเคลื่อนไหวไม่สามารถเป็น "{channel_name}" ได้', 'danger')
                conn.rollback()
                return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            if channel_name == 'ออนไลน์':
                if not new_online_platform_id_str: # ใช้ new_online_platform_id_str เดิมสำหรับ OUT ช่องทางออนไลน์
                    flash('กรุณาระบุ "แพลตฟอร์มออนไลน์" สำหรับช่องทาง "ออนไลน์"', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_online_platform_id = int(new_online_platform_id_str)
                except ValueError:
                    flash('ข้อมูลแพลตฟอร์มออนไลน์ไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_online_platform_id = None # Clear if not online
            
            if channel_name == 'ค้าส่ง':
                if not new_wholesale_customer_id_str: # ใช้ new_wholesale_customer_id_str เดิมสำหรับ OUT ค้าส่ง
                    flash('กรุณาระบุ "ชื่อลูกค้าค้าส่ง" สำหรับช่องทาง "ค้าส่ง"', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_wholesale_customer_id = int(new_wholesale_customer_id_str)
                except ValueError:
                    flash('ข้อมูลชื่อลูกค้าค้าส่งไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_wheel_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_wholesale_customer_id = None # Make sure this is None for other OUT channels
            
            new_return_customer_type = None

        try:
            old_type = movement_data['type']
            old_quantity_change = movement_data['quantity_change']

            database.update_wheel_movement(conn, movement_id, new_notes, bill_image_url_to_db, 
                                            new_type, new_quantity_change,
                                            final_new_channel_id, final_new_online_platform_id, 
                                            final_new_wholesale_customer_id, new_return_customer_type)

            wheel_info = f"{movement_data['brand'].title()} {movement_data['model'].title()}"
            message = (
                f"แก้ไขสต็อกแม็ก: {wheel_info} "
                f"จาก [{old_type}] {old_quantity_change} วง เป็น [{new_type}] {new_quantity_change} วง "
                f"โดย {current_user.username}"
            )
            database.add_notification(conn, message, current_user.id)
            conn.commit()
            
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกแม็กสำเร็จ!', 'success')
            cache.delete_memoized(get_cached_unread_notification_count)
            cache.delete_memoized(get_all_wheels_list_cached)
            return redirect(url_for('stock.daily_stock_report'))
        except ValueError as e:
            flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            conn.rollback()
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')
            conn.rollback()

    return render_template('edit_wheel_movement.html', 
                           movement=movement_data, 
                           current_user=current_user,
                           sales_channels=sales_channels,
                           online_platforms=online_platforms,
                           wholesale_customers=wholesale_customers)
                           
    
@bp.route('/delete_tire_movement/<int:movement_id>', methods=['POST'])
@login_required
def delete_tire_movement_action(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการลบข้อมูลการเคลื่อนไหวสต็อกยาง', 'danger')
        return redirect(request.referrer or url_for('stock.daily_stock_report'))

    conn = get_db()
    try:
        item_details, move_type, quantity_change = database.delete_tire_movement(conn, movement_id, current_user.id)
        message = (f"ลบรายการสต็อกยาง: {item_details} ประเภท [{move_type}] จำนวน {quantity_change} เส้น โดย {current_user.username}")
        database.add_notification(conn, message, current_user.id)
        conn.commit()

        # เปลี่ยนจาก flash เป็น session
        session['post_action_sweetalert'] = {'icon': 'success', 'message': 'ลบรายการเคลื่อนไหวยางและปรับสต็อกเรียบร้อย!'}

        cache.delete_memoized(get_all_tires_list_cached)
        cache.delete_memoized(get_cached_unread_notification_count)

    except ValueError as e:
        # เปลี่ยนจาก flash เป็น session
        session['post_action_sweetalert'] = {'icon': 'error', 'message': f'เกิดข้อผิดพลาด: {e}'}
        conn.rollback()
    except Exception as e:
        # เปลี่ยนจาก flash เป็น session
        session['post_action_sweetalert'] = {'icon': 'error', 'title': 'เกิดข้อผิดพลาด', 'text': f'เกิดข้อผิดพลาดในการลบข้อมูล: {e}'}
        conn.rollback()

    return redirect(request.referrer or url_for('stock.daily_stock_report'))


@bp.route('/delete_wheel_movement/<int:movement_id>', methods=['POST'])
@login_required
def delete_wheel_movement_action(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการลบข้อมูลการเคลื่อนไหวสต็อกแม็ก', 'danger')
        return redirect(url_for('stock.daily_stock_report'))
    
    conn = get_db()
    try:
        # ส่ง user id เข้าไปในฟังก์ชัน และรับค่าที่ return กลับมา
        item_details, move_type, quantity_change = database.delete_wheel_movement(conn, movement_id, current_user.id)
        
        # สร้าง Notification
        message = (
            f"ลบรายการสต็อกแม็ก: {item_details} "
            f"ประเภท [{move_type}] จำนวน {quantity_change} วง "
            f"โดย {current_user.username}"
        )
        database.add_notification(conn, message, current_user.id)
        conn.commit() # Commit ทั้งการลบและการเพิ่ม Notification
        
        session['post_action_sweetalert'] = {'icon': 'success', 'message': 'ลบรายการเคลื่อนไหวแม็กและปรับสต็อกเรียบร้อย!'}
        
        # เคลียร์ Cache
        cache.delete_memoized(get_all_wheels_list_cached)
        cache.delete_memoized(get_cached_unread_notification_count) # เคลียร์ cache กระดิ่ง

    except ValueError as e:
        session['post_action_sweetalert'] = {'icon': 'error', 'message': f'เกิดข้อผิดพลาด: {e}'}
        conn.rollback()
    except Exception as e:
        session['post_action_sweetalert'] = {'icon': 'error', 'title': 'เกิดข้อผิดพลาด', 'text': f'เกิดข้อผิดพลาดในการลบข้อมูล: {e}'}
        conn.rollback()
    
    return redirect(request.referrer or url_for('stock.daily_stock_report'))

@bp.route('/edit_spare_part_movement/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_spare_part_movement(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลการเคลื่อนไหวสต็อกอะไหล่', 'danger')
        return redirect(url_for('stock.daily_stock_report'))

    conn = get_db()
    movement = database.get_spare_part_movement(conn, movement_id)

    if movement is None:
        flash('ไม่พบข้อมูลการเคลื่อนไหวที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.daily_stock_report'))

    movement_data = dict(movement)
    movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])

    sales_channels = database.get_all_sales_channels(conn)
    online_platforms = database.get_all_online_platforms(conn)
    wholesale_customers = database.get_all_wholesale_customers(conn)

    if request.method == 'POST':
        new_notes = request.form.get('notes', '').strip()
        new_type = request.form['type']
        new_quantity_change = int(request.form['quantity_change'])
        bill_image_file = request.files.get('bill_image')
        delete_existing_image = request.form.get('delete_existing_image') == 'on'

        current_image_url = movement_data['image_filename']
        bill_image_url_to_db = current_image_url

        # --- START: MODIFIED UPLOAD/DELETE LOGIC ---
        if delete_existing_image:
            if current_app.config['CLOUDINARY_AVAILABLE']:
                if current_image_url and "res.cloudinary.com" in current_image_url:
                    public_id_match = re.search(r'v\d+/([^/.]+)', current_image_url)
                    if public_id_match:
                        public_id = public_id_match.group(1)
                        try:
                            cloudinary.uploader.destroy(public_id)
                        except Exception as e:
                            print(f"Error deleting old spare part movement image from Cloudinary: {e}")
            else:
                if current_image_url and "/uploads/" in current_image_url:
                    old_filename = current_image_url.split('/')[-1]
                    old_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
            bill_image_url_to_db = None

        if bill_image_file and bill_image_file.filename != '':
            if allowed_image_file(bill_image_file.filename):
                try:
                    if current_app.config['CLOUDINARY_AVAILABLE']:
                        upload_result = cloudinary.uploader.upload(bill_image_file)
                        new_image_url = upload_result['secure_url']
                    else:
                        # Use local storage
                        original_filename = secure_filename(bill_image_file.filename)
                        file_extension = os.path.splitext(original_filename)[1]
                        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                        
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                        bill_image_file.save(filepath)
                        new_image_url = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                    bill_image_url_to_db = new_image_url
                except Exception as e:
                    flash(f'เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิล: {e}', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                flash('ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
        # --- END: MODIFIED UPLOAD/DELETE LOGIC ---

        new_channel_id_str = request.form.get('channel_id')
        new_online_platform_id_str = request.form.get('online_platform_id')
        new_wholesale_customer_id_str = request.form.get('wholesale_customer_id')
        new_return_customer_type = request.form.get('return_customer_type')
        new_return_wholesale_customer_id_str = request.form.get('return_wholesale_customer_id')
        new_return_online_platform_id_str = request.form.get('return_online_platform_id')

        final_new_channel_id = int(new_channel_id_str) if new_channel_id_str else None
        final_new_online_platform_id = None
        final_new_wholesale_customer_id = None

        channel_name = database.get_sales_channel_name(conn, final_new_channel_id)

        if new_type == 'IN':
            if channel_name != 'ซื้อเข้า':
                flash('สำหรับประเภท "รับเข้า" ช่องทางการเคลื่อนไหวต้องเป็น "ซื้อเข้า" เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            new_return_customer_type = None
        elif new_type == 'RETURN':
            if channel_name != 'รับคืน':
                flash('สำหรับประเภท "รับคืน/ตีคืน" ช่องทางการเคลื่อนไหวต้องเป็น "รับคืน" เท่านั้น', 'danger')
                conn.rollback()
                return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            if not new_return_customer_type:
                flash('กรุณาระบุ "คืนจาก" สำหรับประเภท "รับคืน/ตีคืน"', 'danger')
                conn.rollback()
                return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)

            if new_return_customer_type == 'ออนไลน์':
                if not new_return_online_platform_id_str:
                    flash('กรุณาระบุ "แพลตฟอร์มออนไลน์ที่คืน" สำหรับการคืนจาก "ออนไลน์"', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_online_platform_id = int(new_return_online_platform_id_str)
                except ValueError:
                    flash('ข้อมูลแพลตฟอร์มออนไลน์ที่คืนไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_online_platform_id = None

            if new_return_customer_type == 'หน้าร้านร้านยาง':
                if not new_return_wholesale_customer_id_str:
                    flash('กรุณาระบุ "ชื่อร้านยาง" สำหรับการคืนจาก "หน้าร้าน (ร้านยาง)"', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_wholesale_customer_id = int(new_return_wholesale_customer_id_str)
                except ValueError:
                    flash('ข้อมูลชื่อร้านยางไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)

        elif new_type == 'OUT':
            if channel_name == 'ซื้อเข้า' or channel_name == 'รับคืน':
                flash(f'สำหรับประเภท "จ่ายออก" ช่องทางการเคลื่อนไหวไม่สามารถเป็น "{channel_name}" ได้', 'danger')
                conn.rollback()
                return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            if channel_name == 'ออนไลน์':
                if not new_online_platform_id_str:
                    flash('กรุณาระบุ "แพลตฟอร์มออนไลน์" สำหรับช่องทาง "ออนไลน์"', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_online_platform_id = int(new_online_platform_id_str)
                except ValueError:
                    flash('ข้อมูลแพลตฟอร์มออนไลน์ไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_online_platform_id = None

            if channel_name == 'ค้าส่ง':
                if not new_wholesale_customer_id_str:
                    flash('กรุณาระบุ "ชื่อลูกค้าค้าส่ง" สำหรับช่องทาง "ค้าส่ง"', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
                try:
                    final_new_wholesale_customer_id = int(new_wholesale_customer_id_str)
                except ValueError:
                    flash('ข้อมูลชื่อลูกค้าค้าส่งไม่ถูกต้อง', 'danger')
                    conn.rollback()
                    return render_template('edit_spare_part_movement.html', movement=movement_data, current_user=current_user, sales_channels=sales_channels, online_platforms=online_platforms, wholesale_customers=wholesale_customers)
            else:
                final_new_wholesale_customer_id = None

            new_return_customer_type = None

        try:
            old_type = movement_data['type']
            old_quantity_change = movement_data['quantity_change']

            database.update_spare_part_movement(conn, movement_id, new_notes, bill_image_url_to_db,
                                            new_type, new_quantity_change,
                                            final_new_channel_id, final_new_online_platform_id,
                                            final_new_wholesale_customer_id, new_return_customer_type)

            spare_part_info = f"{movement_data['spare_part_name']} ({movement_data.get('spare_part_brand', 'ไม่ระบุยี่ห้อ')})"
            message = (
                f"แก้ไขสต็อกอะไหล่: {spare_part_info} "
                f"จาก [{old_type}] {old_quantity_change} ชิ้น เป็น [{new_type}] {new_quantity_change} ชิ้น "
                f"โดย {current_user.username}"
            )
            database.add_notification(conn, message, current_user.id)
            conn.commit()
            cache.delete_memoized(get_all_spare_parts_cached)
            cache.delete_memoized(get_all_spare_parts_list_cached)
            cache.delete_memoized(get_cached_unread_notification_count)
            flash('แก้ไขข้อมูลการเคลื่อนไหวสต็อกอะไหล่สำเร็จ!', 'success')
            return redirect(url_for('stock.daily_stock_report', tab='spare_part_movements_history'))
        except ValueError as e:
            flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            conn.rollback()
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {e}', 'danger')
            conn.rollback()

    return render_template('edit_spare_part_movement.html',
                           movement=movement_data,
                           current_user=current_user,
                           sales_channels=sales_channels,
                           online_platforms=online_platforms,
                           wholesale_customers=wholesale_customers)


@bp.route('/delete_spare_part_movement/<int:movement_id>', methods=['POST'])
@login_required
def delete_spare_part_movement_action(movement_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการลบข้อมูลการเคลื่อนไหวสต็อกอะไหล่', 'danger')
        return redirect(url_for('stock.daily_stock_report'))

    conn = get_db()
    try:
        # ส่ง user id เข้าไปในฟังก์ชัน และรับค่าที่ return กลับมา
        item_details, move_type, quantity_change = database.delete_spare_part_movement(conn, movement_id, current_user.id)
        
        # สร้าง Notification
        message = (
            f"ลบรายการสต็อกอะไหล่: {item_details} "
            f"ประเภท [{move_type}] จำนวน {quantity_change} ชิ้น "
            f"โดย {current_user.username}"
        )
        database.add_notification(conn, message, current_user.id)
        conn.commit() # Commit ทั้งการลบและการเพิ่ม Notification

        session['post_action_sweetalert'] = {'icon': 'success', 'message': 'ลบรายการเคลื่อนไหวอะไหล่และปรับสต็อกเรียบร้อย!'}

        # เคลียร์ Cache
        cache.delete_memoized(get_all_spare_parts_cached)
        cache.delete_memoized(get_all_spare_parts_list_cached)
        cache.delete_memoized(get_cached_unread_notification_count) # เคลียร์ cache กระดิ่ง
        cache.delete_memoized(get_cached_spare_part_brands)

    except ValueError as e:
        session['post_action_sweetalert'] = {'icon': 'error', 'message': f'เกิดข้อผิดพลาด: {e}'}
        conn.rollback()
    except Exception as e:
        session['post_action_sweetalert'] = {'icon': 'error', 'title': 'เกิดข้อผิดพลาด', 'text': f'เกิดข้อผิดพลาดในการลบข้อมูล: {e}'}
        conn.rollback()

    return redirect(request.referrer or url_for('stock.daily_stock_report'))

@bp.route('/summary_details')
@login_required
def summary_details():
    if not (current_user.is_admin() or current_user.is_editor() or current_user.is_wholesale_sales()):
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))
        
    conn = get_db()
    
    # Get filters from URL
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date', start_date_str)
    channel_id = request.args.get('channel_id', type=int)
    wholesale_customer_id = request.args.get('wholesale_customer_id', type=int)
    online_platform_id = request.args.get('online_platform_id', type=int)
    return_customer_type = request.args.get('return_customer_type', type=str)
    move_type = request.args.get('move_type', type=str)
    item_type_filter = request.args.get('item_type')

    # Set date range
    try:
        start_date_obj = BKK_TZ.localize(datetime.strptime(start_date_str, '%Y-%m-%d')).replace(hour=0, minute=0, second=0, microsecond=0) if start_date_str else get_bkk_time().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date_obj = BKK_TZ.localize(datetime.strptime(end_date_str, '%Y-%m-%d')).replace(hour=23, minute=59, second=59, microsecond=999999) if end_date_str else get_bkk_time().replace(hour=23, minute=59, second=59, microsecond=999999)
    except (ValueError, TypeError):
        flash("รูปแบบวันที่ใน URL ไม่ถูกต้อง", "warning")
        return redirect(url_for('stock.summary_stock_report'))

    display_range_str = f"จาก {start_date_obj.strftime('%d %b %Y')} ถึง {end_date_obj.strftime('%d %b %Y')}"
    
    # --- START: CORRECTED SECTION ---

    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"
    
    base_params = [start_date_obj.isoformat(), end_date_obj.isoformat()]
    
    # Helper function to build WHERE clause conditions without table prefixes
    def build_query_parts():
        conditions = []
        # Start params with the base date range
        params = list(base_params)
        if channel_id:
            conditions.append(f"channel_id = {placeholder}")
            params.append(channel_id)
        if wholesale_customer_id:
            conditions.append(f"wholesale_customer_id = {placeholder}")
            params.append(wholesale_customer_id)
        if online_platform_id:
            conditions.append(f"online_platform_id = {placeholder}")
            params.append(online_platform_id)
        if return_customer_type:
            conditions.append(f"return_customer_type = {placeholder}")
            params.append(return_customer_type)
        if move_type:
            conditions.append(f"type = {placeholder}")
            params.append(move_type)
        
        # Join conditions with 'AND'
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params

    cursor = conn.cursor()
    tire_movements_raw = []
    wheel_movements_raw = []
    spare_part_movements_raw = []

    # Fetch tire data if needed
    if not item_type_filter or item_type_filter == 'tire':
        tire_where_clause, tire_params = build_query_parts()
        tire_movements_query = f"""
            SELECT tm.id, tm.timestamp, tm.type, tm.quantity_change, tm.notes,
                   t.brand, t.model, t.size, u.username AS user_username,
                   tm.image_filename,
                   sc.name as channel_name,
                   op.name as online_platform_name,
                   wc.name as wholesale_customer_name,
                   tm.return_customer_type
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            LEFT JOIN users u ON tm.user_id = u.id
            LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
            LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
            WHERE tm.timestamp BETWEEN {placeholder} AND {placeholder} AND {tire_where_clause}
            ORDER BY tm.timestamp DESC
        """
        cursor.execute(tire_movements_query, tuple(tire_params))
        tire_movements_raw = cursor.fetchall()

    # Fetch wheel data if needed
    if not item_type_filter or item_type_filter == 'wheel':
        wheel_where_clause, wheel_params = build_query_parts()
        wheel_movements_query = f"""
            SELECT wm.id, wm.timestamp, wm.type, wm.quantity_change, wm.notes,
                   w.brand, w.model, w.diameter, u.username AS user_username,
                   wm.image_filename,
                   sc.name as channel_name,
                   op.name as online_platform_name,
                   wc.name as wholesale_customer_name,
                   wm.return_customer_type
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            LEFT JOIN users u ON wm.user_id = u.id
            LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
            LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
            WHERE wm.timestamp BETWEEN {placeholder} AND {placeholder} AND {wheel_where_clause}
            ORDER BY wm.timestamp DESC
        """
        print("DEBUG WHEEL QUERY:", wheel_movements_query) # Add this for debugging
        cursor.execute(wheel_movements_query, tuple(wheel_params))
        wheel_movements_raw = cursor.fetchall()

    # Fetch spare part data if needed
    if not item_type_filter or item_type_filter == 'spare_part':
        spare_part_where_clause, spare_part_params = build_query_parts()
        spare_part_movements_query = f"""
            SELECT spm.id, spm.timestamp, spm.type, spm.quantity_change, spm.notes,
                   sp.brand, sp.name, u.username AS user_username,
                   spm.image_filename,
                   sc.name as channel_name,
                   op.name as online_platform_name,
                   wc.name as wholesale_customer_name,
                   spm.return_customer_type
            FROM spare_part_movements spm
            JOIN spare_parts sp ON spm.spare_part_id = sp.id
            LEFT JOIN users u ON spm.user_id = u.id
            LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
            LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
            WHERE spm.timestamp BETWEEN {placeholder} AND {placeholder} AND {spare_part_where_clause}
            ORDER BY spm.timestamp DESC
        """
        print("DEBUG SPARE PART QUERY:", spare_part_movements_query)
        cursor.execute(spare_part_movements_query, tuple(spare_part_params))
        spare_part_movements_raw = cursor.fetchall()
    
    cursor.close()
    
    # --- END: CORRECTED SECTION ---

    # Process timestamps (this part is correct)
    processed_tire_movements = []
    for movement in tire_movements_raw:
        movement_data = dict(movement)
        movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])
        processed_tire_movements.append(movement_data)

    processed_wheel_movements = []
    for movement in wheel_movements_raw:
        movement_data = dict(movement)
        movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])
        processed_wheel_movements.append(movement_data)

    processed_spare_part_movements = []
    for movement in spare_part_movements_raw:
        movement_data = dict(movement)
        movement_data['timestamp'] = database.convert_to_bkk_time(movement_data['timestamp'])
        processed_spare_part_movements.append(movement_data)

    return render_template('summary_details.html',
                            display_range_str=display_range_str,
                            tire_movements=processed_tire_movements,
                            wheel_movements=processed_wheel_movements,
                            spare_part_movements=processed_spare_part_movements,
                            current_user=current_user)

# --- daily_stock_report (assuming this is already in your app.py) ---
@bp.route('/daily_stock_report')
@login_required
def daily_stock_report():
    if not (current_user.is_admin() or current_user.is_editor() or current_user.is_wholesale_sales() or current_user.is_accountant()):
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้ารายงานสต็อกประจำวัน', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    report_date_str = request.args.get('date')
    
    try:
        report_date_obj = datetime.strptime(report_date_str, '%Y-%m-%d').date() if report_date_str else get_bkk_time().date()
    except (ValueError, TypeError):
        flash("รูปแบบวันที่ไม่ถูกต้อง, ใช้ YYYY-MM-DD", "danger")
        report_date_obj = get_bkk_time().date()
        
    # --- START: ✨ ส่วนที่เพิ่มเข้ามา ---
    THAI_MONTHS_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    
    # สร้างข้อความแสดงผลวันที่แบบไทย
    day = report_date_obj.day
    month_th = THAI_MONTHS_FULL[report_date_obj.month - 1]
    year_be = report_date_obj.year + 543
    display_date_str = f"{day} {month_th} {year_be}"

    if report_date_str:
        try:
            report_datetime_obj = BKK_TZ.localize(datetime.strptime(report_date_str, '%Y-%m-%d')).replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            flash("รูปแบบวันที่ไม่ถูกต้อง กรุณาใช้ YYYY-MM-DD", "danger")
            conn.rollback()
            report_datetime_obj = get_bkk_time().replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_datetime_obj = get_bkk_time().replace(hour=0, minute=0, second=0, microsecond=0)

    # --- START: โค้ดที่แก้ไข ---
    # กำหนดเวลาเริ่มต้นและสิ้นสุดของวันใน BKK Timezone สำหรับการ Query ที่ถูกต้อง
    start_of_report_day_iso = report_datetime_obj.isoformat()
    end_of_report_day_iso = report_datetime_obj.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    # --- END: โค้ดที่แก้ไข ---
    
    report_date = report_datetime_obj.date()
    is_psycopg2_conn = "psycopg2" in str(type(conn))
    timestamp_cast = "::timestamptz" if is_psycopg2_conn else ""
    placeholder = "%s" if is_psycopg2_conn else "?"

    # --- Tire Report Data ---
    # --- START: โค้ดที่แก้ไข ---
    tire_movements_query_today = f"""
        SELECT
            tm.id, tm.timestamp, tm.type, tm.quantity_change, tm.remaining_quantity, tm.image_filename, tm.notes,
            t.id AS tire_main_id, t.brand, t.model, t.size,
            u.username AS user_username,
            sc.name AS channel_name,
            op.name AS online_platform_name,
            wc.name AS wholesale_customer_name,
            tm.return_customer_type
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        LEFT JOIN users u ON tm.user_id = u.id
        LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
        LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
        WHERE tm.timestamp BETWEEN {placeholder} AND {placeholder}
        ORDER BY tm.timestamp DESC
    """
    if is_psycopg2_conn:
        cursor = conn.cursor()
        cursor.execute(tire_movements_query_today, (start_of_report_day_iso, end_of_report_day_iso))
        tire_movements_raw_today = cursor.fetchall()
        cursor.close()
    else:
        tire_movements_raw_today = conn.execute(tire_movements_query_today, (start_of_report_day_iso, end_of_report_day_iso)).fetchall()
    # --- END: โค้ดที่แก้ไข ---

    processed_tire_movements_raw_today = []
    for movement in tire_movements_raw_today:
        movement_data = dict(movement)
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_tire_movements_raw_today.append(movement_data)
    tire_movements_raw = processed_tire_movements_raw_today
    
    # ... (ส่วนที่เหลือของโค้ดในการคำนวณและประมวลผลข้อมูลยาง ไม่มีการเปลี่ยนแปลง) ...
    tire_quantities_before_report = defaultdict(int)
    tire_ids_involved = set()
    for movement in tire_movements_raw:
        tire_ids_involved.add(movement['tire_main_id'])

    day_before_report = report_datetime_obj.replace(hour=0, minute=0, second=0) - timedelta(microseconds=1)
    day_before_report_iso = day_before_report.isoformat()

    sql_date_filter_end_of_day = report_datetime_obj.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    distinct_tire_ids_query_all_history = f"""
        SELECT DISTINCT tire_id
        FROM tire_movements
        WHERE timestamp <= {placeholder}{timestamp_cast}
    """
    if is_psycopg2_conn:
        cursor = conn.cursor() # New cursor for this query
        cursor.execute(distinct_tire_ids_query_all_history, (sql_date_filter_end_of_day,))
        rows = cursor.fetchall()
        cursor.close()
    else:
        rows = conn.execute(distinct_tire_ids_query_all_history, (sql_date_filter_end_of_day,)).fetchall()

    for row in rows:
        tire_ids_involved.add(row['tire_id'])


    tire_quantities_before_report = defaultdict(int)
    if tire_ids_involved:
        ids_list = list(tire_ids_involved)
        placeholders_for_in = ', '.join([placeholder] * len(ids_list))

        query_initial_quantities = f"""
        SELECT
        tire_id,
        COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0) as initial_quantity
        FROM tire_movements
        WHERE tire_id IN ({placeholders_for_in}) AND timestamp < {placeholder}{timestamp_cast}
        GROUP BY tire_id
        """
        params = ids_list + [day_before_report_iso]

        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(query_initial_quantities, tuple(params))
            initial_quantities_rows = cursor.fetchall()
            cursor.close()
        else:
            # For SQLite, remove the ::timestamptz cast if it exists in the placeholder string
            query_sqlite = query_initial_quantities.replace(timestamp_cast, "")
            initial_quantities_rows = conn.execute(query_sqlite, tuple(params)).fetchall()

        for row in initial_quantities_rows:
            tire_quantities_before_report[row['tire_id']] = row['initial_quantity']

    sorted_detailed_tire_report = []
    # Add channel_name, online_platform_name, wholesale_customer_name, return_customer_type to detailed_tire_report
    detailed_tire_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0, 'remaining_quantity': 0, 'tire_main_id': None, 'brand': '', 'model': '', 'size': '', 'movements': []}) #

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
            detailed_tire_report[key]['OUT'] += movement['quantity_change'] # สะสมยอดจ่ายออก
            detailed_tire_report[key]['remaining_quantity'] -= movement['quantity_change']
        elif movement['type'] == 'RETURN': #
            detailed_tire_report[key]['RETURN'] += movement['quantity_change'] # สะสมยอดรับคืน
            detailed_tire_report[key]['remaining_quantity'] += movement['quantity_change'] # รับคืนเพิ่มสต็อก

        # เพิ่มรายละเอียด movement เข้าไปในลิสต์
        detailed_tire_report[key]['movements'].append({
            'id': movement['id'],
            'timestamp': movement['timestamp'],
            'type': movement['type'],
            'quantity_change': movement['quantity_change'],
            'notes': movement['notes'],
            'image_filename': movement['image_filename'],
            'user_username': movement['user_username'],
            'channel_name': movement['channel_name'],
            'online_platform_name': movement['online_platform_name'],
            'wholesale_customer_name': movement['wholesale_customer_name'],
            'return_customer_type': movement['return_customer_type']
        })

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


    tire_brand_summaries = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0, 'current_quantity_sum': 0}) #
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
                'RETURN': summary_data['RETURN'], #
                'remaining_quantity': summary_data['current_quantity_sum']
            })

        sorted_detailed_tire_report.append({
            'is_summary': False,
            'brand': brand,
            'model': model,
            'size': size,
            'IN': data['IN'],
            'OUT': data['OUT'],
            'RETURN': data['RETURN'], #
            'remaining_quantity': data['remaining_quantity'],
            'movements': data['movements'] # Pass individual movements for detail view
        })

        tire_brand_summaries[brand]['IN'] += data['IN']
        tire_brand_summaries[brand]['OUT'] += data['OUT']
        tire_brand_summaries[brand]['RETURN'] += data['RETURN'] #
        tire_brand_summaries[brand]['current_quantity_sum'] += data['remaining_quantity']
        last_brand = brand

    if last_brand is not None:
        summary_data = tire_brand_summaries[last_brand]
        sorted_detailed_tire_report.append({
            'is_summary': True,
            'brand': last_brand,
            'IN': summary_data['IN'],
            'OUT': summary_data['OUT'],
            'RETURN': summary_data['RETURN'], #
            'remaining_quantity': summary_data['current_quantity_sum']
        })

    # --- Wheel Report Data ---
    # --- START: โค้ดที่แก้ไข ---
    wheel_movements_query_today = f"""
        SELECT
            wm.id, wm.timestamp, wm.type, wm.quantity_change, wm.remaining_quantity, wm.image_filename, wm.notes,
            w.id AS wheel_main_id, w.brand, w.model, w.diameter, w.pcd, w.width,
            u.username AS user_username,
            sc.name AS channel_name,
            op.name AS online_platform_name,
            wc.name AS wholesale_customer_name,
            wm.return_customer_type
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        LEFT JOIN users u ON wm.user_id = u.id
        LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
        LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
        WHERE wm.timestamp BETWEEN {placeholder} AND {placeholder}
        ORDER BY wm.timestamp DESC
    """
    if is_psycopg2_conn:
        cursor_wheel = conn.cursor()
        cursor_wheel.execute(wheel_movements_query_today, (start_of_report_day_iso, end_of_report_day_iso))
        wheel_movements_raw_today = cursor_wheel.fetchall()
        cursor_wheel.close()
    else:
        wheel_movements_raw_today = conn.execute(wheel_movements_query_today, (start_of_report_day_iso, end_of_report_day_iso)).fetchall()
    # --- END: โค้ดที่แก้ไข ---

    processed_wheel_movements_raw_today = []
    for movement in wheel_movements_raw_today:
        movement_data = dict(movement)
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_wheel_movements_raw_today.append(movement_data)
    wheel_movements_raw = processed_wheel_movements_raw_today
    
    # ... (ส่วนที่เหลือของโค้ดในการคำนวณและประมวลผลข้อมูลแม็ก ไม่มีการเปลี่ยนแปลง) ...
    wheel_quantities_before_report = defaultdict(int)
    wheel_ids_involved = set()
    for movement in wheel_movements_raw:
        wheel_ids_involved.add(movement['wheel_main_id'])

    day_before_report = report_datetime_obj.replace(hour=0, minute=0, second=0) - timedelta(microseconds=1)
    day_before_report_iso = day_before_report.isoformat()

    distinct_wheel_ids_query_all_history = f"""
    SELECT DISTINCT wheel_id
    FROM wheel_movements
    WHERE timestamp <= {placeholder}{timestamp_cast}
    """
    if is_psycopg2_conn:
        cursor_wheel = conn.cursor()
        cursor_wheel.execute(distinct_wheel_ids_query_all_history, (sql_date_filter_end_of_day,))
        rows = cursor_wheel.fetchall()
        cursor_wheel.close()
    else:
        rows = conn.execute(distinct_wheel_ids_query_all_history, (sql_date_filter_end_of_day,)).fetchall()

    for row in rows:
        wheel_ids_involved.add(row['wheel_id'])


    if wheel_ids_involved:
        ids_list = list(wheel_ids_involved)
        placeholders_for_in = ', '.join([placeholder] * len(ids_list))

        query_initial_quantities = f"""
            SELECT
                wheel_id,
                COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0) as initial_quantity
            FROM wheel_movements
            WHERE wheel_id IN ({placeholders_for_in}) AND timestamp < {placeholder}{timestamp_cast}
            GROUP BY wheel_id
        """
        params = ids_list + [day_before_report_iso]

        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(query_initial_quantities, tuple(params))
            initial_quantities_rows = cursor.fetchall()
            cursor.close()
        else:
            query_sqlite = query_initial_quantities.replace(timestamp_cast, "")
            initial_quantities_rows = conn.execute(query_sqlite, tuple(params)).fetchall()

        for row in initial_quantities_rows:
            wheel_quantities_before_report[row['wheel_id']] = row['initial_quantity']


    sorted_detailed_wheel_report = []
    # Add channel_name, online_platform_name, wholesale_customer_name, return_customer_type to detailed_wheel_report
    detailed_wheel_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0, 'remaining_quantity': 0, 'wheel_main_id': None, 'brand': '', 'model': '', 'diameter': None, 'pcd': '', 'width': None, 'movements': []}) #

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
            detailed_wheel_report[key]['OUT'] += movement['quantity_change'] # สะสมยอดจ่ายออก
            detailed_wheel_report[key]['remaining_quantity'] -= movement['quantity_change']
        elif movement['type'] == 'RETURN': #
            detailed_wheel_report[key]['RETURN'] += movement['quantity_change'] # สะสมยอดรับคืน
            detailed_wheel_report[key]['remaining_quantity'] += movement['quantity_change'] # รับคืนเพิ่มสต็อก

        # เพิ่มรายละเอียด movement เข้าไปในลิสต์
        detailed_wheel_report[key]['movements'].append({
            'id': movement['id'],
            'timestamp': movement['timestamp'],
            'type': movement['type'],
            'quantity_change': movement['quantity_change'],
            'notes': movement['notes'],
            'image_filename': movement['image_filename'],
            'user_username': movement['user_username'],
            'channel_name': movement['channel_name'],
            'online_platform_name': movement['online_platform_name'],
            'wholesale_customer_name': movement['wholesale_customer_name'],
            'return_customer_type': movement['return_customer_type']
        })

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


    wheel_brand_summaries = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0, 'current_quantity_sum': 0}) #
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
                'RETURN': summary_data['RETURN'], #
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
            'RETURN': data['RETURN'], #
            'remaining_quantity': data['remaining_quantity'],
            'movements': data['movements'] # Pass individual movements for detail view
        })

        wheel_brand_summaries[brand]['IN'] += data['IN']
        wheel_brand_summaries[brand]['OUT'] += data['OUT']
        wheel_brand_summaries[brand]['RETURN'] += data['RETURN'] #
        wheel_brand_summaries[brand]['current_quantity_sum'] += data['remaining_quantity']
        last_brand = brand

    if last_brand is not None:
        summary_data = wheel_brand_summaries[last_brand]
        sorted_detailed_wheel_report.append({
            'is_summary': True,
            'brand': last_brand,
            'IN': summary_data['IN'],
            'OUT': summary_data['OUT'],
            'RETURN': summary_data['RETURN'], #
            'remaining_quantity': summary_data['current_quantity_sum']
        })

    # --- NEW: Spare Part Report Data ---
    # --- START: โค้ดที่แก้ไข ---
    spare_part_movements_query_today = f"""
        SELECT
            spm.id, spm.timestamp, spm.type, spm.quantity_change, spm.remaining_quantity, spm.image_filename, spm.notes,
            sp.id AS spare_part_main_id, sp.name AS spare_part_name, sp.part_number, sp.brand AS spare_part_brand,
            spc.name AS category_name,
            u.username AS user_username,
            sc.name AS channel_name,
            op.name AS online_platform_name,
            wc.name AS wholesale_customer_name,
            spm.return_customer_type
        FROM spare_part_movements spm
        JOIN spare_parts sp ON spm.spare_part_id = sp.id
        LEFT JOIN spare_part_categories spc ON sp.category_id = spc.id
        LEFT JOIN users u ON spm.user_id = u.id
        LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
        LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
        WHERE spm.timestamp BETWEEN {placeholder} AND {placeholder}
        ORDER BY spm.timestamp DESC
    """
    if is_psycopg2_conn:
        cursor_spare_part = conn.cursor()
        cursor_spare_part.execute(spare_part_movements_query_today, (start_of_report_day_iso, end_of_report_day_iso))
        spare_part_movements_raw_today = cursor_spare_part.fetchall()
        cursor_spare_part.close()
    else:
        spare_part_movements_raw_today = conn.execute(spare_part_movements_query_today, (start_of_report_day_iso, end_of_report_day_iso)).fetchall()
    # --- END: โค้ดที่แก้ไข ---

    processed_spare_part_movements_raw_today = []
    for movement in spare_part_movements_raw_today:
        movement_data = dict(movement)
        movement_data['timestamp'] = convert_to_bkk_time(movement_data['timestamp'])
        processed_spare_part_movements_raw_today.append(movement_data)
    spare_part_movements_raw = processed_spare_part_movements_raw_today
    
    # ... (ส่วนที่เหลือของโค้ดในการคำนวณและประมวลผลข้อมูลอะไหล่ ไม่มีการเปลี่ยนแปลง) ...
    spare_part_quantities_before_report = defaultdict(int)
    spare_part_ids_involved = set()
    for movement in spare_part_movements_raw:
        spare_part_ids_involved.add(movement['spare_part_main_id'])

    day_before_report = report_datetime_obj.replace(hour=0, minute=0, second=0) - timedelta(microseconds=1)
    day_before_report_iso = day_before_report.isoformat()

    distinct_spare_part_ids_query_all_history = f"""
    SELECT DISTINCT spare_part_id
    FROM spare_part_movements
    WHERE timestamp <= {placeholder}{timestamp_cast}
    """
    if is_psycopg2_conn:
        cursor_spare_part = conn.cursor()
        cursor_spare_part.execute(distinct_spare_part_ids_query_all_history, (sql_date_filter_end_of_day,))
        rows = cursor_spare_part.fetchall()
        cursor_spare_part.close()
    else:
        rows = conn.execute(distinct_spare_part_ids_query_all_history, (sql_date_filter_end_of_day,)).fetchall()

    for row in rows:
        spare_part_ids_involved.add(row['spare_part_id'])


    if spare_part_ids_involved:
        ids_list = list(spare_part_ids_involved)
        placeholders_for_in = ', '.join([placeholder] * len(ids_list))

        query_initial_quantities = f"""
            SELECT
                spare_part_id,
                COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0) as initial_quantity
            FROM spare_part_movements
            WHERE spare_part_id IN ({placeholders_for_in}) AND timestamp < {placeholder}{timestamp_cast}
            GROUP BY spare_part_id
        """
        params = ids_list + [day_before_report_iso]

        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(query_initial_quantities, tuple(params))
            initial_quantities_rows = cursor.fetchall()
            cursor.close()
        else:
            query_sqlite = query_initial_quantities.replace(timestamp_cast, "")
            initial_quantities_rows = conn.execute(query_sqlite, tuple(params)).fetchall()

        for row in initial_quantities_rows:
            spare_part_quantities_before_report[row['spare_part_id']] = row['initial_quantity']

    sorted_detailed_spare_part_report = []
    detailed_spare_part_report = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0, 'remaining_quantity': 0, 'spare_part_main_id': None, 'name': '', 'brand': '', 'part_number': '', 'category_name': '', 'movements': []})

    for movement in spare_part_movements_raw:
        key = (movement['spare_part_name'], movement['spare_part_brand'], movement['part_number'])
        spare_part_id = movement['spare_part_main_id']

        if key not in detailed_spare_part_report:
            detailed_spare_part_report[key]['spare_part_main_id'] = spare_part_id
            detailed_spare_part_report[key]['name'] = movement['spare_part_name']
            detailed_spare_part_report[key]['brand'] = movement['spare_part_brand']
            detailed_spare_part_report[key]['part_number'] = movement['part_number']
            detailed_spare_part_report[key]['category_name'] = movement['category_name']
            detailed_spare_part_report[key]['remaining_quantity'] = spare_part_quantities_before_report[spare_part_id]

        if movement['type'] == 'IN':
            detailed_spare_part_report[key]['IN'] += movement['quantity_change']
            detailed_spare_part_report[key]['remaining_quantity'] += movement['quantity_change']
        elif movement['type'] == 'OUT':
            detailed_spare_part_report[key]['OUT'] += movement['quantity_change']
            detailed_spare_part_report[key]['remaining_quantity'] -= movement['quantity_change']
        elif movement['type'] == 'RETURN':
            detailed_spare_part_report[key]['RETURN'] += movement['quantity_change']
            detailed_spare_part_report[key]['remaining_quantity'] += movement['quantity_change']

        detailed_spare_part_report[key]['movements'].append({
            'id': movement['id'],
            'timestamp': movement['timestamp'],
            'type': movement['type'],
            'quantity_change': movement['quantity_change'],
            'notes': movement['notes'],
            'image_filename': movement['image_filename'],
            'user_username': movement['user_username'],
            'channel_name': movement['channel_name'],
            'online_platform_name': movement['online_platform_name'],
            'wholesale_customer_name': movement['wholesale_customer_name'],
            'return_customer_type': movement['return_customer_type']
        })

    for spare_part_id, qty in spare_part_quantities_before_report.items():
        if not any(item['spare_part_main_id'] == spare_part_id for item in spare_part_movements_raw):
            spare_part_info = database.get_spare_part(conn, spare_part_id)
            if spare_part_info and not spare_part_info['is_deleted']:
                key = (spare_part_info['name'], spare_part_info['brand'], spare_part_info['part_number'])
                if key not in detailed_spare_part_report:
                    detailed_spare_part_report[key]['spare_part_main_id'] = spare_part_id
                    detailed_spare_part_report[key]['name'] = spare_part_info['name']
                    detailed_spare_part_report[key]['brand'] = spare_part_info['brand']
                    detailed_spare_part_report[key]['part_number'] = spare_part_info['part_number']
                    detailed_spare_part_report[key]['category_name'] = spare_part_info['category_name']
                    detailed_spare_part_report[key]['remaining_quantity'] = qty

    spare_part_category_summaries = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0, 'current_quantity_sum': 0})
    sorted_unique_spare_part_items = sorted(detailed_spare_part_report.items(), key=lambda x: (x[1]['category_name'] or '', x[0]))

    last_category = None
    for (name, brand, part_number), data in sorted_unique_spare_part_items:
        current_category = data['category_name'] or 'ไม่ระบุหมวดหมู่'
        if last_category is not None and current_category != last_category:
            summary_data = spare_part_category_summaries[last_category]
            sorted_detailed_spare_part_report.append({
                'is_summary': True,
                'type': 'category_summary',
                'category_name': last_category,
                'IN': summary_data['IN'],
                'OUT': summary_data['OUT'],
                'RETURN': summary_data['RETURN'],
                'remaining_quantity': summary_data['current_quantity_sum']
            })

        sorted_detailed_spare_part_report.append({
            'is_summary': False,
            'name': name,
            'brand': brand,
            'part_number': part_number,
            'category_name': current_category,
            'IN': data['IN'],
            'OUT': data['OUT'],
            'RETURN': data['RETURN'],
            'remaining_quantity': data['remaining_quantity'],
            'movements': data['movements']
        })

        spare_part_category_summaries[current_category]['IN'] += data['IN']
        spare_part_category_summaries[current_category]['OUT'] += data['OUT']
        spare_part_category_summaries[current_category]['RETURN'] += data['RETURN']
        spare_part_category_summaries[current_category]['current_quantity_sum'] += data['remaining_quantity']
        last_category = current_category

    if last_category is not None:
        summary_data = spare_part_category_summaries[last_category]
        sorted_detailed_spare_part_report.append({
            'is_summary': True,
            'type': 'category_summary',
            'category_name': last_category,
            'IN': summary_data['IN'],
            'OUT': summary_data['OUT'],
            'RETURN': summary_data['RETURN'],
            'remaining_quantity': summary_data['current_quantity_sum']
        })


    # Calculate totals for summary section at the bottom of the report
    tire_total_in = sum(item['IN'] for item in sorted_detailed_tire_report if not item['is_summary'])
    tire_total_out = sum(item['OUT'] for item in sorted_detailed_tire_report if not item['is_summary'])
    tire_total_return = sum(item['RETURN'] for item in sorted_detailed_tire_report if not item['is_summary']) #

    tire_total_remaining_for_report_date = 0
    query_total_before_tires = f"""
        SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
        FROM tire_movements
        WHERE timestamp < {placeholder}{timestamp_cast}
    """
    if is_psycopg2_conn:
        cursor = conn.cursor()
        cursor.execute(query_total_before_tires, (start_of_report_day_iso,))
        initial_total_tires = cursor.fetchone()[0] or 0
        cursor.close()
    else:
        initial_total_tires = conn.execute(query_total_before_tires, (start_of_report_day_iso,)).fetchone()[0] or 0

    tire_total_remaining_for_report_date = initial_total_tires + tire_total_in + tire_total_return - tire_total_out #


    wheel_total_in = sum(item['IN'] for item in sorted_detailed_wheel_report if not item['is_summary'])
    wheel_total_out = sum(item['OUT'] for item in sorted_detailed_wheel_report if not item['is_summary'])
    wheel_total_return = sum(item['RETURN'] for item in sorted_detailed_wheel_report if not item['is_summary']) #

    wheel_total_remaining_for_report_date = 0
    query_total_before_wheels = f"""
        SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
        FROM wheel_movements
        WHERE timestamp < {placeholder}{timestamp_cast};
    """
    if is_psycopg2_conn:
        cursor = conn.cursor()
        cursor.execute(query_total_before_wheels, (start_of_report_day_iso,))
        initial_total_wheels = cursor.fetchone()[0] or 0
        cursor.close()
    else:
        initial_total_wheels = conn.execute(query_total_before_wheels, (start_of_report_day_iso,)).fetchone()[0] or 0

    wheel_total_remaining_for_report_date = initial_total_wheels + wheel_total_in + wheel_total_return - wheel_total_out #

    # NEW: Spare Part Totals
    spare_part_total_in = sum(item['IN'] for item in sorted_detailed_spare_part_report if not item['is_summary'])
    spare_part_total_out = sum(item['OUT'] for item in sorted_detailed_spare_part_report if not item['is_summary'])
    spare_part_total_return = sum(item['RETURN'] for item in sorted_detailed_spare_part_report if not item['is_summary'])

    spare_part_total_remaining_for_report_date = 0
    query_total_before_spare_parts = f"""
        SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
        FROM spare_part_movements
        WHERE timestamp < {placeholder}{timestamp_cast};
    """
    if is_psycopg2_conn:
        cursor = conn.cursor()
        cursor.execute(query_total_before_spare_parts, (start_of_report_day_iso,))
        initial_total_spare_parts = cursor.fetchone()[0] or 0
        cursor.close()
    else:
        initial_total_spare_parts = conn.execute(query_total_before_spare_parts, (start_of_report_day_iso,)).fetchone()[0] or 0

    spare_part_total_remaining_for_report_date = initial_total_spare_parts + spare_part_total_in + spare_part_total_return - spare_part_total_out


    # Calculate yesterday and tomorrow dates using the datetime object
    yesterday_date_calc = report_datetime_obj - timedelta(days=1)
    tomorrow_date_calc = report_datetime_obj + timedelta(days=1)

    return render_template('daily_stock_report.html',
                           display_date_str=display_date_str, # <--- ส่งค่าภาษาไทยที่ถูกต้อง
                           report_date_obj=report_date_obj,
                           report_date_param=report_date_obj.strftime('%Y-%m-%d'),
                           yesterday_date_param=(report_date_obj - timedelta(days=1)).strftime('%Y-%m-%d'),
                           tomorrow_date_param=(report_date_obj + timedelta(days=1)).strftime('%Y-%m-%d'),
                           tire_report=sorted_detailed_tire_report,
                           wheel_report=sorted_detailed_wheel_report,
                           spare_part_report=sorted_detailed_spare_part_report,
                           tire_total_in=tire_total_in,
                           tire_total_out=tire_total_out,
                           tire_total_return=tire_total_return,
                           tire_total_remaining=tire_total_remaining_for_report_date,
                           wheel_total_in=wheel_total_in,
                           wheel_total_out=wheel_total_out,
                           wheel_total_return=wheel_total_return,
                           wheel_total_remaining=wheel_total_remaining_for_report_date,
                           spare_part_total_in=spare_part_total_in,
                           spare_part_total_out=spare_part_total_out,
                           spare_part_total_return=spare_part_total_return,
                           spare_part_total_remaining=spare_part_total_remaining_for_report_date,
                           tire_movements_raw=tire_movements_raw,
                           wheel_movements_raw=wheel_movements_raw,
                           spare_part_movements_raw=spare_part_movements_raw,
                           current_user=current_user
                          )


# --- NEW: Summary Stock Report Route ---
@bp.route('/summary_stock_report')
@login_required
def summary_stock_report():
    if not (current_user.is_admin() or current_user.is_editor() or current_user.is_wholesale_sales() or current_user.is_accountant()):
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้ารายงานสรุปสต็อก', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    try:
        if not start_date_str or not end_date_str:
            today = get_bkk_time().date()
            first_day_of_month = today.replace(day=1)
            start_date_obj = BKK_TZ.localize(datetime.combine(first_day_of_month, datetime.min.time()))
            end_date_obj = BKK_TZ.localize(datetime.combine(today, datetime.max.time()))
        else:
            start_date_obj = BKK_TZ.localize(datetime.strptime(start_date_str, '%Y-%m-%d')).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date_obj = BKK_TZ.localize(datetime.strptime(end_date_str, '%Y-%m-%d')).replace(hour=23, minute=59, second=59, microsecond=999999)
            if start_date_obj > end_date_obj:
                raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
    except (ValueError, TypeError) as e:
        flash(f"รูปแบบวันที่ไม่ถูกต้อง: {e}", "danger")
        today = get_bkk_time().date()
        first_day_of_month = today.replace(day=1)
        start_date_obj = BKK_TZ.localize(datetime.combine(first_day_of_month, datetime.min.time()))
        end_date_obj = BKK_TZ.localize(datetime.combine(today, datetime.max.time()))

    THAI_MONTHS_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    start_day = start_date_obj.day
    start_month_th = THAI_MONTHS_FULL[start_date_obj.month - 1]
    start_year_be = start_date_obj.year + 543
    end_day = end_date_obj.day
    end_month_th = THAI_MONTHS_FULL[end_date_obj.month - 1]
    end_year_be = end_date_obj.year + 543

    if start_year_be == end_year_be:
        if start_month_th == end_month_th and start_day == end_day:
            display_range_str = f"วันที่ {start_day} {start_month_th} {start_year_be}"
        elif start_month_th == end_month_th:
            display_range_str = f"จากวันที่ {start_day} - {end_day} {start_month_th} {start_year_be}"
        else:
            display_range_str = f"จากวันที่ {start_day} {start_month_th} - {end_day} {end_month_th} {end_year_be}"
    else:
        display_range_str = f"จากวันที่ {start_day} {start_month_th} {start_year_be} - {end_day} {end_month_th} {end_year_be}"

    is_psycopg2_conn = "psycopg2" in str(type(conn))
    timestamp_cast = "::timestamptz" if is_psycopg2_conn else ""
    placeholder = "%s" if is_psycopg2_conn else "?"
    start_of_period_iso = start_date_obj.isoformat()
    end_of_period_iso = end_date_obj.isoformat()

    sorted_tire_movements_by_channel = OrderedDict()
    sorted_wheel_movements_by_channel = OrderedDict()
    sorted_spare_part_movements_by_channel = OrderedDict()
    tires_by_brand_for_summary_report = OrderedDict()
    wheels_by_brand_for_summary_report = OrderedDict()
    spare_parts_by_category_and_brand_for_summary_report = OrderedDict()
    tire_brand_totals_for_summary_report = OrderedDict()
    wheel_brand_totals_for_summary_report = OrderedDict()
    spare_part_category_totals_for_summary_report = OrderedDict()

    tire_movements_by_channel_data = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': [], 'online_platforms': defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0}), 'wholesale_customers': defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0})})
    wheel_movements_by_channel_data = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': [], 'online_platforms': defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0}), 'wholesale_customers': defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0})})
    spare_part_movements_by_channel_data = defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': [], 'online_platforms': defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0}), 'wholesale_customers': defaultdict(lambda: {'IN': 0, 'OUT': 0, 'RETURN': 0})})


    # --- Tire Movements by Channel, Platform, Customer (Summary by Channel) ---
    tire_movements_raw_detailed = []
    tire_channel_summary_query = f"""
        SELECT
            sc.id AS channel_id,
            op.id AS online_platform_id,
            wc.id AS wholesale_customer_id,
            COALESCE(sc.name, 'ไม่ระบุช่องทาง') AS channel_name,
            COALESCE(op.name, 'ไม่ระบุแพลตฟอร์ม') AS online_platform_name,
            COALESCE(wc.name, 'ไม่ระบุลูกค้า') AS wholesale_customer_name,
            tm.type,
            SUM(tm.quantity_change) AS total_quantity,
            COALESCE(tm.return_customer_type, 'ไม่ระบุประเภทคืน') AS return_customer_type
        FROM tire_movements tm
        LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
        LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
        WHERE tm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast}
        GROUP BY sc.id, op.id, wc.id, sc.name, op.name, wc.name, tm.type, tm.return_customer_type
        ORDER BY sc.name, op.name, wc.name, tm.type;
    """
    tire_channel_summary_params = (start_of_period_iso, end_of_period_iso)

    try:
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(tire_channel_summary_query, tire_channel_summary_params)
            tire_movements_raw_detailed = cursor.fetchall()
            cursor.close()
        else:
            query_for_sqlite = tire_channel_summary_query.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            tire_movements_raw_detailed = conn.execute(query_for_sqlite, tire_channel_summary_params).fetchall()

        for movement_row in tire_movements_raw_detailed:
            # โค้ดทั้งหมดนี้ต้องอยู่ "ข้างใน" for loop
            row_data = dict(movement_row)
            channel_name_from_db = row_data['channel_name']

            channel_id_from_db = row_data['channel_id']
            online_platform_id_from_db = row_data['online_platform_id']
            wholesale_customer_id_from_db = row_data['wholesale_customer_id']

            online_platform_name = row_data['online_platform_name']
            wholesale_customer_name = row_data['wholesale_customer_name']
            move_type = row_data['type']
            total_qty = int(row_data['total_quantity'])
            return_customer_type = row_data['return_customer_type']

            main_channel_key = channel_name_from_db

            if 'channel_id' not in tire_movements_by_channel_data[main_channel_key]:
                tire_movements_by_channel_data[main_channel_key]['channel_id'] = channel_id_from_db

            if move_type == 'RETURN':
                tire_movements_by_channel_data[main_channel_key]['RETURN'].append({
                    'quantity': total_qty,
                    'type': return_customer_type,
                    'online_platform_name': online_platform_name,
                    'wholesale_customer_name': wholesale_customer_name,
                    'online_platform_id': online_platform_id_from_db,
                    'wholesale_customer_id': wholesale_customer_id_from_db
                })
            else:
                tire_movements_by_channel_data[main_channel_key][move_type] += total_qty

            if main_channel_key == 'ออนไลน์':
                if online_platform_name and online_platform_name != 'ไม่ระบุแพลตฟอร์ม':
                    if online_platform_name not in tire_movements_by_channel_data[main_channel_key]['online_platforms']:
                         tire_movements_by_channel_data[main_channel_key]['online_platforms'][online_platform_name] = {'IN': 0, 'OUT': 0, 'RETURN': 0}
                    tire_movements_by_channel_data[main_channel_key]['online_platforms'][online_platform_name][move_type] += total_qty
                    tire_movements_by_channel_data[main_channel_key]['online_platforms'][online_platform_name]['id'] = online_platform_id_from_db

            elif main_channel_key == 'ค้าส่ง':
                if wholesale_customer_name and wholesale_customer_name != 'ไม่ระบุลูกค้า':
                    if wholesale_customer_name not in tire_movements_by_channel_data[main_channel_key]['wholesale_customers']:
                        tire_movements_by_channel_data[main_channel_key]['wholesale_customers'][wholesale_customer_name] = {'IN': 0, 'OUT': 0, 'RETURN': 0}
                    tire_movements_by_channel_data[main_channel_key]['wholesale_customers'][wholesale_customer_name][move_type] += total_qty
                    tire_movements_by_channel_data[main_channel_key]['wholesale_customers'][wholesale_customer_name]['id'] = wholesale_customer_id_from_db

        # โค้ด 2 บรรทัดนี้ต้องอยู่ "นอก" for loop แต่ยังอยู่ "ใน" try
        sorted_tire_movements_by_channel = OrderedDict(sorted(tire_movements_by_channel_data.items()))

        for channel_name_sort, data_sort in sorted_tire_movements_by_channel.items():
            if 'online_platforms' in data_sort:
                data_sort['online_platforms'] = OrderedDict(sorted(data_sort['online_platforms'].items()))
            if 'wholesale_customers' in data_sort:
                data_sort['wholesale_customers'] = OrderedDict(sorted(data_sort['wholesale_customers'].items()))

    except Exception as e:
        print(f"ERROR: Failed to fetch detailed tire movements for summary (Channel): {e}")
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลสรุปยางตามช่องทาง: {e}", "danger")
        conn.rollback()


    # --- Wheel Movements by Channel, Platform, Customer (Summary by Channel) ---
    wheel_movements_raw_detailed = []
    wheel_channel_summary_query = f"""
        SELECT
            sc.id AS channel_id,
            op.id AS online_platform_id,
            wc.id AS wholesale_customer_id,
            COALESCE(sc.name, 'ไม่ระบุช่องทาง') AS channel_name,
            COALESCE(op.name, 'ไม่ระบุแพลตฟอร์ม') AS online_platform_name,
            COALESCE(wc.name, 'ไม่ระบุลูกค้า') AS wholesale_customer_name,
            wm.type,
            SUM(wm.quantity_change) AS total_quantity,
            COALESCE(wm.return_customer_type, 'ไม่ระบุประเภทคืน') AS return_customer_type
        FROM wheel_movements wm
        LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
        LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
        WHERE wm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast}
        GROUP BY sc.id, op.id, wc.id, sc.name, op.name, wc.name, wm.type, wm.return_customer_type
        ORDER BY sc.name, op.name, wc.name, wm.type;
    """
    wheel_channel_summary_params = (start_of_period_iso, end_of_period_iso)

    try:
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(wheel_channel_summary_query, wheel_channel_summary_params)
            wheel_movements_raw_detailed = cursor.fetchall()
            cursor.close()
        else:
            query_for_sqlite = wheel_channel_summary_query.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            wheel_movements_raw_detailed = conn.execute(query_for_sqlite, wheel_channel_summary_params).fetchall()

        # flash(f"DEBUG (Wheel Raw Detailed for Channel Summary): {wheel_movements_raw_detailed}", "info") # DEBUGGING LINE

        for movement_row in wheel_movements_raw_detailed:
            row_data = dict(movement_row)
            channel_name_from_db = row_data['channel_name']
            online_platform_name = row_data['online_platform_name']
            wholesale_customer_name = row_data['wholesale_customer_name']
            move_type = row_data['type']
            total_qty = int(row_data['total_quantity'])
            return_customer_type = row_data['return_customer_type']

            main_channel_key = channel_name_from_db

            # Aggregate to main channel totals
            if move_type == 'RETURN': # หากเป็น RETURN ให้เก็บรายละเอียดไว้ใน list
                wheel_movements_by_channel_data[main_channel_key]['RETURN'].append({
                    'quantity': total_qty,
                    'type': return_customer_type,
                    'online_platform_name': online_platform_name,
                    'wholesale_customer_name': wholesale_customer_name
                })
            else: # สำหรับ IN และ OUT ให้รวมยอดปกติ
                wheel_movements_by_channel_data[main_channel_key][move_type] += total_qty

            # Aggregate to sub-channel totals if applicable
            if main_channel_key == 'ออนไลน์':
                if online_platform_name and online_platform_name != 'ไม่ระบุแพลตฟอร์ม':
                    wheel_movements_by_channel_data[main_channel_key]['online_platforms'][online_platform_name][move_type] += total_qty
            elif main_channel_key == 'ค้าส่ง':
                if wholesale_customer_name and wholesale_customer_name != 'ไม่ระบุลูกค้า':
                    wheel_movements_by_channel_data[main_channel_key]['wholesale_customers'][wholesale_customer_name][move_type] += total_qty

        sorted_wheel_movements_by_channel = OrderedDict(sorted(wheel_movements_by_channel_data.items()))
        for channel_name_sort, data_sort in sorted_wheel_movements_by_channel.items():
            if 'online_platforms' in data_sort:
                data_sort['online_platforms'] = OrderedDict(sorted(data_sort['online_platforms'].items()))
            if 'wholesale_customers' in data_sort:
                data_sort['wholesale_customers'] = OrderedDict(sorted(data_sort['wholesale_customers'].items()))

        # flash(f"DEBUG (Sorted Wheel by Channel for Template): {sorted_wheel_movements_by_channel}", "info") # DEBUGGING LINE

    except Exception as e:
        print(f"ERROR: Failed to fetch detailed wheel movements for summary (Channel): {e}")
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลสรุปแม็กตามช่องทาง: {e}", "danger")
        conn.rollback()

    # --- NEW: Spare Part Movements by Channel, Platform, Customer (Summary by Channel) ---
    spare_part_movements_raw_detailed = []
    spare_part_channel_summary_query = f"""
        SELECT
            sc.id AS channel_id,
            op.id AS online_platform_id,
            wc.id AS wholesale_customer_id,
            COALESCE(sc.name, 'ไม่ระบุช่องทาง') AS channel_name,
            COALESCE(op.name, 'ไม่ระบุแพลตฟอร์ม') AS online_platform_name,
            COALESCE(wc.name, 'ไม่ระบุลูกค้า') AS wholesale_customer_name,
            spm.type,
            SUM(spm.quantity_change) AS total_quantity,
            COALESCE(spm.return_customer_type, 'ไม่ระบุประเภทคืน') AS return_customer_type
        FROM spare_part_movements spm
        LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
        LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
        WHERE spm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast}
        GROUP BY sc.id, op.id, wc.id, sc.name, op.name, wc.name, spm.type, spm.return_customer_type
        ORDER BY sc.name, op.name, wc.name, spm.type;
    """
    spare_part_channel_summary_params = (start_of_period_iso, end_of_period_iso)

    try:
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(spare_part_channel_summary_query, spare_part_channel_summary_params)
            spare_part_movements_raw_detailed = cursor.fetchall()
            cursor.close()
        else:
            query_for_sqlite = spare_part_channel_summary_query.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            spare_part_movements_raw_detailed = conn.execute(query_for_sqlite, spare_part_channel_summary_params).fetchall()

        for movement_row in spare_part_movements_raw_detailed:
            row_data = dict(movement_row)
            channel_name_from_db = row_data['channel_name']
            online_platform_name = row_data['online_platform_name']
            wholesale_customer_name = row_data['wholesale_customer_name']
            move_type = row_data['type']
            total_qty = int(row_data['total_quantity'])
            return_customer_type = row_data['return_customer_type']

            main_channel_key = channel_name_from_db

            if move_type == 'RETURN':
                spare_part_movements_by_channel_data[main_channel_key]['RETURN'].append({
                    'quantity': total_qty,
                    'type': return_customer_type,
                    'online_platform_name': online_platform_name,
                    'wholesale_customer_name': wholesale_customer_name
                })
            else:
                spare_part_movements_by_channel_data[main_channel_key][move_type] += total_qty

            if main_channel_key == 'ออนไลน์':
                if online_platform_name and online_platform_name != 'ไม่ระบุแพลตฟอร์ม':
                    spare_part_movements_by_channel_data[main_channel_key]['online_platforms'][online_platform_name][move_type] += total_qty
            elif main_channel_key == 'ค้าส่ง':
                if wholesale_customer_name and wholesale_customer_name != 'ไม่ระบุลูกค้า':
                    spare_part_movements_by_channel_data[main_channel_key]['wholesale_customers'][wholesale_customer_name][move_type] += total_qty

        sorted_spare_part_movements_by_channel = OrderedDict(sorted(spare_part_movements_by_channel_data.items()))
        for channel_name_sort, data_sort in sorted_spare_part_movements_by_channel.items():
            if 'online_platforms' in data_sort:
                data_sort['online_platforms'] = OrderedDict(sorted(data_sort['online_platforms'].items()))
            if 'wholesale_customers' in data_sort:
                data_sort['wholesale_customers'] = OrderedDict(sorted(data_sort['wholesale_customers'].items()))

    except Exception as e:
        print(f"ERROR: Failed to fetch detailed spare part movements for summary (Channel): {e}")
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลสรุปอะไหล่ตามช่องทาง: {e}", "danger")
        conn.rollback()


    # Calculate overall totals for the summary section
    overall_tire_initial = 0
    overall_wheel_initial = 0
    overall_spare_part_initial = 0 # NEW

    # MODIFIED: Correctly sum the 'quantity' from the list of RETURN details
    overall_tire_in_period = int(sum(data.get('IN', 0) for data in tire_movements_by_channel_data.values()))
    overall_tire_out_period = int(sum(data.get('OUT', 0) for data in tire_movements_by_channel_data.values()))
    # Correct sum for RETURN: iterate through the list of dictionaries and sum 'quantity'
    overall_tire_return_period = int(sum(
        item['quantity'] for data in tire_movements_by_channel_data.values()
        for item in data.get('RETURN', []) # Get the list, default to empty list if not present
    ))

    overall_wheel_in_period = int(sum(data.get('IN', 0) for data in wheel_movements_by_channel_data.values()))
    overall_wheel_out_period = int(sum(data.get('OUT', 0) for data in wheel_movements_by_channel_data.values()))
    # Correct sum for RETURN: iterate through the list of dictionaries and sum 'quantity'
    overall_wheel_return_period = int(sum(
        item['quantity'] for data in wheel_movements_by_channel_data.values()
        for item in data.get('RETURN', []) # Get the list, default to empty list if not present
    ))

    # NEW: Spare Part overall totals
    overall_spare_part_in_period = int(sum(data.get('IN', 0) for data in spare_part_movements_by_channel_data.values()))
    overall_spare_part_out_period = int(sum(data.get('OUT', 0) for data in spare_part_movements_by_channel_data.values()))
    overall_spare_part_return_period = int(sum(
        item['quantity'] for data in spare_part_movements_by_channel_data.values()
        for item in data.get('RETURN', [])
    ))

    try:
        # Total initial stock (sum of all IN/RETURN - all OUT up to start_of_period_iso)
        query_overall_initial_tires = f"""
            SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
            FROM tire_movements
            WHERE timestamp < {placeholder}{timestamp_cast};
        """
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(query_overall_initial_tires, (start_of_period_iso,))
            overall_tire_initial = int(cursor.fetchone()[0] or 0)
            cursor.close()
        else:
            query_for_sqlite = query_overall_initial_tires.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            overall_tire_initial = int(conn.execute(query_for_sqlite, (start_of_period_iso,)).fetchone()[0] or 0)
        # flash(f"DEBUG (Overall Tire Initial): {overall_tire_initial}", "info")
    except Exception as e:
        print(f"ERROR: Failed to fetch overall initial tire stock: {e}")
        flash(f"เกิดข้อผิดพลาดในการคำนวณสต็อกยางเริ่มต้น: {e}", "danger")
        conn.rollback()
        overall_tire_initial = 0

    try:
        query_overall_initial_wheels = f"""
            SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
            FROM wheel_movements
            WHERE timestamp < {placeholder}{timestamp_cast};
        """
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(query_overall_initial_wheels, (start_of_period_iso,))
            overall_wheel_initial = int(cursor.fetchone()[0] or 0)
            cursor.close()
        else:
            query_for_sqlite = query_overall_initial_wheels.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            overall_wheel_initial = int(conn.execute(query_for_sqlite, (start_of_period_iso,)).fetchone()[0] or 0)
        # flash(f"DEBUG (Overall Wheel Initial): {overall_wheel_initial}", "info")
    except Exception as e:
        print(f"ERROR: Failed to fetch overall initial wheel stock: {e}")
        flash(f"เกิดข้อผิดพลาดในการคำนวณสต็อกแม็กเริ่มต้น: {e}", "danger")
        conn.rollback()
        overall_wheel_initial = 0

    # NEW: Query for overall initial spare part stock
    try:
        query_overall_initial_spare_parts = f"""
            SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
            FROM spare_part_movements
            WHERE timestamp < {placeholder}{timestamp_cast};
        """
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(query_overall_initial_spare_parts, (start_of_period_iso,))
            overall_spare_part_initial = int(cursor.fetchone()[0] or 0)
            cursor.close()
        else:
            query_for_sqlite = query_overall_initial_spare_parts.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            overall_spare_part_initial = int(conn.execute(query_for_sqlite, (start_of_period_iso,)).fetchone()[0] or 0)
    except Exception as e:
        print(f"ERROR: Failed to fetch overall initial spare part stock: {e}")
        flash(f"เกิดข้อผิดพลาดในการคำนวณสต็อกอะไหล่เริ่มต้น: {e}", "danger")
        conn.rollback()
        overall_spare_part_initial = 0


    # Total final stock (initial + movements within period)
    overall_tire_final = overall_tire_initial + overall_tire_in_period + overall_tire_return_period - overall_tire_out_period
    overall_wheel_final = overall_wheel_initial + overall_wheel_in_period + overall_wheel_return_period - overall_wheel_out_period
    overall_spare_part_final = overall_spare_part_initial + overall_spare_part_in_period + overall_spare_part_return_period - overall_spare_part_out_period # NEW

    try:
        # --- สำหรับรายงานการเคลื่อนไหวสต็อกยางตามยี่ห้อและขนาด (tires_by_brand_for_summary_report) ---
        tire_detailed_item_query = f"""
            SELECT
                t.id AS tire_id,
                t.brand,
                t.model,
                t.size,
                COALESCE(SUM(CASE WHEN tm.type = 'IN' AND tm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN tm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS IN_qty,
                COALESCE(SUM(CASE WHEN tm.type = 'OUT' AND tm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN tm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS OUT_qty,
                COALESCE(SUM(CASE WHEN tm.type = 'RETURN' AND tm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN tm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS RETURN_qty,
                COALESCE((
                    SELECT SUM(CASE WHEN prev_tm.type = 'IN' OR prev_tm.type = 'RETURN' THEN prev_tm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE -prev_tm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} END)
                    FROM tire_movements prev_tm
                    WHERE prev_tm.tire_id = t.id AND prev_tm.timestamp < {placeholder}{timestamp_cast}
                ), 0) AS initial_qty_before_period
            FROM tires t
            LEFT JOIN tire_movements tm ON tm.tire_id = t.id
            WHERE t.is_deleted = FALSE
            GROUP BY t.id, t.brand, t.model, t.size
            HAVING (
                -- Has any movement in the period (IN, OUT, RETURN)
                COALESCE(SUM(CASE WHEN tm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN 1 ELSE 0 END), 0) > 0
                -- OR had initial stock before the period (sum of movements before period)
                OR COALESCE((SELECT SUM(CASE WHEN prev_tm.type = 'IN' OR prev_tm.type = 'RETURN' THEN prev_tm.quantity_change ELSE -prev_tm.quantity_change END) FROM tire_movements prev_tm WHERE prev_tm.tire_id = t.id AND prev_tm.timestamp < {placeholder}{timestamp_cast}), 0) <> 0
                -- OR has current quantity (current_quantity is from the 'tires' table itself)
                OR COALESCE(t.quantity, 0) > 0
            )
            ORDER BY t.brand, t.model, t.size;
        """

        tire_item_params = (
            start_of_period_iso, end_of_period_iso, # IN_qty sum (param 1,2)
            start_of_period_iso, end_of_period_iso, # OUT_qty sum (param 3,4)
            start_of_period_iso, end_of_period_iso, # RETURN_qty sum (param 5,6)
            start_of_period_iso, # initial_qty_before_period subquery (param 7)
            start_of_period_iso, end_of_period_iso, # HAVING: Any movement in period (param 8,9)
            start_of_period_iso # HAVING: Had initial stock before period (param 10)
            # t.quantity (param 11) is direct column, not a placeholder in query
        )

        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(tire_detailed_item_query, tire_item_params)
            tires_detailed_movements_raw = cursor.fetchall()
            cursor.close()
        else:
            query_for_sqlite = tire_detailed_item_query.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            tires_detailed_movements_raw = conn.execute(query_for_sqlite, tire_item_params).fetchall()

        # flash(f"DEBUG (Tire Item Raw Detailed): {tires_detailed_movements_raw}", "info")

        # tires_by_brand_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ
        for row_data_raw in tires_detailed_movements_raw:
            row = dict(row_data_raw)
            normalized_row = {k.lower(): v for k, v in row.items()}

            brand = normalized_row['brand']
            if brand not in tires_by_brand_for_summary_report:
                tires_by_brand_for_summary_report[brand] = []

            initial_qty = int(normalized_row.get('initial_qty_before_period', 0))
            in_qty = int(normalized_row.get('in_qty', 0))
            out_qty = int(normalized_row.get('out_qty', 0))
            return_qty = int(normalized_row.get('return_qty', 0))

            final_qty = initial_qty + in_qty + return_qty - out_qty

            tires_by_brand_for_summary_report[brand].append({
                'model': normalized_row['model'],
                'size': normalized_row['size'],
                'initial_quantity': initial_qty,
                'IN': in_qty,
                'OUT': out_qty,
                'RETURN': return_qty,
                'final_quantity': final_qty,
            })

        # flash(f"DEBUG (Sorted Tire Item by Brand): {tires_by_brand_for_summary_report}", "info")

    except Exception as e:
        print(f"ERROR: Failed to fetch detailed tire movements (Item): {e}")
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลสรุปยางรายรุ่น: {e}", "danger")
        conn.rollback()
        # tires_by_brand_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ

    try:
        # --- สำหรับรายงานการเคลื่อนไหวสต็อกล้อแม็กตามยี่ห้อและขนาด (wheels_by_brand_for_summary_report) ---
        wheel_detailed_item_query = f"""
            SELECT
                w.id AS wheel_id,
                w.brand, w.model, w.diameter, w.pcd, w.width,
                w.et,
                w.color,
                COALESCE(SUM(CASE WHEN wm.type = 'IN' AND wm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN wm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS IN_qty,
                COALESCE(SUM(CASE WHEN wm.type = 'OUT' AND wm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN wm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS OUT_qty,
                COALESCE(SUM(CASE WHEN wm.type = 'RETURN' AND wm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN wm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS RETURN_qty,
                COALESCE((
                    SELECT SUM(CASE WHEN prev_wm.type = 'IN' OR prev_wm.type = 'RETURN' THEN prev_wm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE -prev_wm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} END)
                    FROM wheel_movements prev_wm
                    WHERE prev_wm.wheel_id = w.id AND prev_wm.timestamp < {placeholder}{timestamp_cast}
                ), 0) AS initial_qty_before_period
            FROM wheels w
            LEFT JOIN wheel_movements wm ON wm.wheel_id = w.id
            WHERE w.is_deleted = FALSE
            GROUP BY w.id, w.brand, w.model, w.diameter, w.pcd, w.width, w.et, w.color
            HAVING (
                -- Has any movement in the period (IN, OUT, RETURN)
                COALESCE(SUM(CASE WHEN wm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN 1 ELSE 0 END), 0) > 0
                -- OR had initial stock before the period (sum of movements before period)
                OR COALESCE((SELECT SUM(CASE WHEN prev_wm.type = 'IN' OR prev_wm.type = 'RETURN' THEN prev_wm.quantity_change ELSE -prev_wm.quantity_change END) FROM wheel_movements prev_wm WHERE prev_wm.wheel_id = w.id AND prev_wm.timestamp < {placeholder}{timestamp_cast}), 0) <> 0
                -- OR has current quantity (current_quantity is from the 'wheels' table itself)
                OR COALESCE(w.quantity, 0) > 0
            )
            ORDER BY w.brand, w.model, w.diameter;
        """
        wheel_item_params = (
            start_of_period_iso, end_of_period_iso, # IN_qty sum (param 1,2)
            start_of_period_iso, end_of_period_iso, # OUT_qty sum (param 3,4)
            start_of_period_iso, end_of_period_iso, # RETURN_qty sum (param 5,6)
            start_of_period_iso, # initial_qty_before_period subquery (param 7)
            start_of_period_iso, end_of_period_iso, # HAVING: Any movement in period (param 8,9)
            start_of_period_iso # HAVING: Had initial stock before period (param 10)
            # w.quantity (param 11) is direct column, not a placeholder in query
        )

        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(wheel_detailed_item_query, wheel_item_params)
            wheels_detailed_movements_raw = cursor.fetchall()
            cursor.close()
        else:
            query_for_sqlite = wheel_detailed_item_query.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            wheels_detailed_movements_raw = conn.execute(query_for_sqlite, wheel_item_params).fetchall()

        # wheels_by_brand_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ
        for row_data_raw in wheels_detailed_movements_raw:
            row = dict(row_data_raw)
            normalized_row = {k.lower(): v for k, v in row.items()}

            brand = normalized_row['brand']
            if brand not in wheels_by_brand_for_summary_report:
                wheels_by_brand_for_summary_report[brand] = []

            initial_qty = int(normalized_row.get('initial_qty_before_period', 0))
            in_qty = int(normalized_row.get('in_qty', 0))
            out_qty = int(normalized_row.get('out_qty', 0))
            return_qty = int(normalized_row.get('return_qty', 0))

            final_qty = initial_qty + in_qty + return_qty - out_qty

            wheels_by_brand_for_summary_report[brand].append({
                'model': normalized_row['model'],
                'diameter': normalized_row['diameter'],
                'pcd': normalized_row['pcd'],
                'width': normalized_row['width'],
                'et': normalized_row['et'],
                'color': normalized_row['color'],
                'initial_quantity': initial_qty,
                'IN': in_qty,
                'OUT': out_qty,
                'RETURN': return_qty,
                'final_quantity': final_qty,
            })

    except Exception as e:
        print(f"ERROR: Failed to fetch detailed wheel movements (Item): {e}")
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลสรุปแม็กรายรุ่น: {e}", "danger")
        conn.rollback()
        # wheels_by_brand_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ

    # NEW: For Spare Part movements summary by item (spare_parts_by_category_and_brand_for_summary_report)
    try:
        spare_part_detailed_item_query = f"""
            SELECT
                sp.id AS spare_part_id,
                sp.name, sp.part_number, sp.brand,
                spc.name AS category_name,
                COALESCE(SUM(CASE WHEN spm.type = 'IN' AND spm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN spm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS IN_qty,
                COALESCE(SUM(CASE WHEN spm.type = 'OUT' AND spm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN spm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS OUT_qty,
                COALESCE(SUM(CASE WHEN spm.type = 'RETURN' AND spm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN spm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE 0 END), 0) AS RETURN_qty,
                COALESCE((
                    SELECT SUM(CASE WHEN prev_spm.type = 'IN' OR prev_spm.type = 'RETURN' THEN prev_spm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} ELSE -prev_spm.quantity_change{"::NUMERIC" if is_psycopg2_conn else ""} END)
                    FROM spare_part_movements prev_spm
                    WHERE prev_spm.spare_part_id = sp.id AND prev_spm.timestamp < {placeholder}{timestamp_cast}
                ), 0) AS initial_qty_before_period
            FROM spare_parts sp
            LEFT JOIN spare_part_movements spm ON spm.spare_part_id = sp.id
            LEFT JOIN spare_part_categories spc ON sp.category_id = spc.id
            WHERE sp.is_deleted = FALSE
            GROUP BY sp.id, sp.name, sp.part_number, sp.brand, spc.name
            HAVING (
                COALESCE(SUM(CASE WHEN spm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast} THEN 1 ELSE 0 END), 0) > 0
                OR COALESCE((SELECT SUM(CASE WHEN prev_spm.type = 'IN' OR prev_spm.type = 'RETURN' THEN prev_spm.quantity_change ELSE -prev_spm.quantity_change END) FROM spare_part_movements prev_spm WHERE prev_spm.spare_part_id = sp.id AND prev_spm.timestamp < {placeholder}{timestamp_cast}), 0) <> 0
                OR COALESCE(sp.quantity, 0) > 0
            )
            ORDER BY spc.name, sp.brand, sp.name;
        """
        spare_part_item_params = (
            start_of_period_iso, end_of_period_iso,
            start_of_period_iso, end_of_period_iso,
            start_of_period_iso, end_of_period_iso,
            start_of_period_iso,
            start_of_period_iso, end_of_period_iso,
            start_of_period_iso
        )

        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(spare_part_detailed_item_query, spare_part_item_params)
            spare_parts_detailed_movements_raw = cursor.fetchall()
            cursor.close()
        else:
            query_for_sqlite = spare_part_detailed_item_query.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
            spare_parts_detailed_movements_raw = conn.execute(query_for_sqlite, spare_part_item_params).fetchall()

        # Process results
        for row_data_raw in spare_parts_detailed_movements_raw:
            row = dict(row_data_raw)
            normalized_row = {k.lower(): v for k, v in row.items()}

            category_name = normalized_row['category_name'] or 'ไม่ระบุหมวดหมู่'
            brand = normalized_row['brand'] or 'ไม่ระบุยี่ห้อ' # Group by brand under category

            if category_name not in spare_parts_by_category_and_brand_for_summary_report:
                spare_parts_by_category_and_brand_for_summary_report[category_name] = OrderedDict()
            if brand not in spare_parts_by_category_and_brand_for_summary_report[category_name]:
                 spare_parts_by_category_and_brand_for_summary_report[category_name][brand] = []

            initial_qty = int(normalized_row.get('initial_qty_before_period', 0))
            in_qty = int(normalized_row.get('in_qty', 0))
            out_qty = int(normalized_row.get('out_qty', 0))
            return_qty = int(normalized_row.get('return_qty', 0))

            final_qty = initial_qty + in_qty + return_qty - out_qty

            spare_parts_by_category_and_brand_for_summary_report[category_name][brand].append({
                'name': normalized_row['name'],
                'part_number': normalized_row['part_number'],
                'initial_quantity': initial_qty,
                'IN': in_qty,
                'OUT': out_qty,
                'RETURN': return_qty,
                'final_quantity': final_qty,
            })

        # Sort brands within each category
        for cat_name, brands_dict in spare_parts_by_category_and_brand_for_summary_report.items():
            spare_parts_by_category_and_brand_for_summary_report[cat_name] = OrderedDict(sorted(brands_dict.items()))


    except Exception as e:
        print(f"ERROR: Failed to fetch detailed spare part movements (Item): {e}")
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลสรุปอะไหล่รายรุ่น: {e}", "danger")
        conn.rollback()


    # --- For summary totals by tire brand (tire_brand_totals_for_summary_report) ---
    try:
        brands_query = """SELECT DISTINCT brand FROM tires WHERE is_deleted = FALSE ORDER BY brand"""
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(brands_query)
            all_tire_brands = [row['brand'] for row in cursor.fetchall()]
            cursor.close()
        else:
            all_tire_brands = [row['brand'] for row in conn.execute(brands_query).fetchall()]

        # tire_brand_totals_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ
        for brand in all_tire_brands:
            query_brand_initial_tire = f"""
                SELECT COALESCE(SUM(CASE WHEN tm.type = 'IN' OR tm.type = 'RETURN' THEN tm.quantity_change ELSE -tm.quantity_change END), 0)
                FROM tire_movements tm
                JOIN tires t ON tm.tire_id = t.id
                WHERE t.brand = {placeholder} AND tm.timestamp < {placeholder}{timestamp_cast};
            """
            if is_psycopg2_conn:
                cursor = conn.cursor()
                cursor.execute(query_brand_initial_tire, (brand, start_of_period_iso))
                brand_initial_qty = int(cursor.fetchone()[0] or 0)
                cursor.close()
            else:
                query_for_sqlite = query_brand_initial_tire.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
                brand_initial_qty = int(conn.execute(query_for_sqlite, (brand, start_of_period_iso)).fetchone()[0] or 0)

            total_in_brand = 0
            total_out_brand = 0
            total_return_brand = 0

            # Aggregate from tires_by_brand_for_summary_report (the item-level data)
            if brand in tires_by_brand_for_summary_report:
                for item in tires_by_brand_for_summary_report[brand]:
                    total_in_brand += item['IN']
                    total_out_brand += item['OUT']
                    total_return_brand += item['RETURN']

            # Only include brands with initial stock, or any movement in the period
            if brand_initial_qty == 0 and total_in_brand == 0 and total_out_brand == 0 and total_return_brand == 0:
                continue

            final_qty_brand = brand_initial_qty + total_in_brand + total_return_brand - total_out_brand

            tire_brand_totals_for_summary_report[brand] = {
                'IN': total_in_brand,
                'OUT': total_out_brand,
                'RETURN': total_return_brand,
                'final_quantity_sum': final_qty_brand,
            }

    except Exception as e:
        print(f"ERROR: Failed to calculate tire brand totals: {e}")
        flash(f"เกิดข้อผิดพลาดในการคำนวณสรุปยางตามยี่ห้อ: {e}", "danger")
        conn.rollback()
        # tire_brand_totals_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ


    # --- For summary totals by wheel brand (wheel_brand_totals_for_summary_report) ---
    try:
        brands_query = """SELECT DISTINCT brand FROM wheels WHERE is_deleted = FALSE ORDER BY brand"""
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(brands_query)
            all_wheel_brands = [row['brand'] for row in cursor.fetchall()]
            cursor.close()
        else:
            all_wheel_brands = [row['brand'] for row in conn.execute(brands_query).fetchall()]

        # wheel_brand_totals_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ
        for brand in all_wheel_brands:
            query_brand_initial_wheel = f"""
                SELECT COALESCE(SUM(CASE WHEN type = 'IN' OR type = 'RETURN' THEN quantity_change ELSE -quantity_change END), 0)
                FROM wheel_movements wm
                JOIN wheels w ON wm.wheel_id = w.id
                WHERE w.brand = {placeholder} AND wm.timestamp < {placeholder}{timestamp_cast};
            """
            if is_psycopg2_conn:
                cursor = conn.cursor()
                cursor.execute(query_brand_initial_wheel, (brand, start_of_period_iso))
                brand_initial_qty = int(cursor.fetchone()[0] or 0)
                cursor.close()
            else:
                query_for_sqlite = query_brand_initial_wheel.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
                brand_initial_qty = int(conn.execute(query_for_sqlite, (brand, start_of_period_iso)).fetchone()[0] or 0)

            total_in_brand = 0
            total_out_brand = 0
            total_return_brand = 0

            # Aggregate from wheels_by_brand_for_summary_report (the item-level data)
            if brand in wheels_by_brand_for_summary_report:
                for item in wheels_by_brand_for_summary_report[brand]:
                    total_in_brand += item['IN']
                    total_out_brand += item['OUT']
                    total_return_brand += item['RETURN']

            if brand_initial_qty == 0 and total_in_brand == 0 and total_out_brand == 0 and total_return_brand == 0:
                continue

            final_qty_brand = brand_initial_qty + total_in_brand + total_return_brand - total_out_brand

            wheel_brand_totals_for_summary_report[brand] = {
                'IN': total_in_brand,
                'OUT': total_out_brand,
                'RETURN': total_return_brand,
                'final_quantity_sum': final_qty_brand,
            }
    except Exception as e:
        print(f"ERROR: Failed to calculate wheel brand totals: {e}")
        flash(f"เกิดข้อผิดพลาดในการคำนวณสรุปแม็กตามยี่ห้อ: {e}", "danger")
        conn.rollback()
        # wheel_brand_totals_for_summary_report ถูกกำหนดค่าเริ่มต้นแล้ว ไม่ต้องกำหนดซ้ำ

    # NEW: For summary totals by spare part category (spare_part_category_totals_for_summary_report)
    try:
        categories_query = """SELECT id, name FROM spare_part_categories ORDER BY name"""
        if is_psycopg2_conn:
            cursor = conn.cursor()
            cursor.execute(categories_query)
            all_spare_part_categories_db = [dict(row) for row in cursor.fetchall()]
            cursor.close()
        else:
            all_spare_part_categories_db = [dict(row) for row in conn.execute(categories_query).fetchall()]

        for category_info in all_spare_part_categories_db:
            cat_id = category_info['id']
            cat_name = category_info['name']

            query_category_initial_spare_part = f"""
                SELECT COALESCE(SUM(CASE WHEN spm.type = 'IN' OR spm.type = 'RETURN' THEN spm.quantity_change ELSE -spm.quantity_change END), 0)
                FROM spare_part_movements spm
                JOIN spare_parts sp ON spm.spare_part_id = sp.id
                WHERE sp.category_id = {placeholder} AND spm.timestamp < {placeholder}{timestamp_cast};
            """
            if is_psycopg2_conn:
                cursor = conn.cursor()
                cursor.execute(query_category_initial_spare_part, (cat_id, start_of_period_iso))
                category_initial_qty = int(cursor.fetchone()[0] or 0)
                cursor.close()
            else:
                query_for_sqlite = query_category_initial_spare_part.replace(f"{timestamp_cast}", "").replace(placeholder, '?')
                category_initial_qty = int(conn.execute(query_for_sqlite, (cat_id, start_of_period_iso)).fetchone()[0] or 0)

            total_in_category = 0
            total_out_category = 0
            total_return_category = 0

            if cat_name in spare_parts_by_category_and_brand_for_summary_report:
                for brand_name, items_list in spare_parts_by_category_and_brand_for_summary_report[cat_name].items():
                    for item in items_list:
                        total_in_category += item['IN']
                        total_out_category += item['OUT']
                        total_return_category += item['RETURN']

            if category_initial_qty == 0 and total_in_category == 0 and total_out_category == 0 and total_return_category == 0:
                continue

            final_qty_category = category_initial_qty + total_in_category + total_return_category - total_out_category

            spare_part_category_totals_for_summary_report[cat_name] = {
                'IN': total_in_category,
                'OUT': total_out_category,
                'RETURN': total_return_category,
                'final_quantity_sum': final_qty_category,
            }
    except Exception as e:
        print(f"ERROR: Failed to calculate spare part category totals: {e}")
        flash(f"เกิดข้อผิดพลาดในการคำนวณสรุปอะไหล่ตามหมวดหมู่: {e}", "danger")
        conn.rollback()


    tires_with_movement = {}
    for brand, items in tires_by_brand_for_summary_report.items():
        # กรองเฉพาะ item ที่มีการเคลื่อนไหว (IN, OUT, หรือ RETURN มากกว่า 0)
        moved_items = [item for item in items if item['IN'] > 0 or item['OUT'] > 0 or item['RETURN'] > 0]
        # ถ้าหลังจากกรองแล้วยังมี item เหลืออยู่ ให้เพิ่ม brand และ item ที่กรองแล้วเข้าไปใน dict ใหม่
        if moved_items:
            tires_with_movement[brand] = moved_items

    wheels_with_movement = {}
    for brand, items in wheels_by_brand_for_summary_report.items():
        moved_items = [item for item in items if item['IN'] > 0 or item['OUT'] > 0 or item['RETURN'] > 0]
        if moved_items:
            wheels_with_movement[brand] = moved_items

    spare_parts_with_movement = {} # NEW
    for category_name, brands_dict in spare_parts_by_category_and_brand_for_summary_report.items():
        category_has_movement = False
        brands_with_movement_in_category = OrderedDict()
        for brand_name, items_list in brands_dict.items():
            moved_items = [item for item in items_list if item['IN'] > 0 or item['OUT'] > 0 or item['RETURN'] > 0]
            if moved_items:
                brands_with_movement_in_category[brand_name] = moved_items
                category_has_movement = True
        if category_has_movement:
            spare_parts_with_movement[category_name] = brands_with_movement_in_category


    return render_template('summary_stock_report.html',
                           start_date_param=start_date_obj.strftime('%Y-%m-%d'),
                           end_date_param=end_date_obj.strftime('%Y-%m-%d'),
                           display_range_str=display_range_str,
                           tire_movements_by_channel=sorted_tire_movements_by_channel,
                           wheel_movements_by_channel=sorted_wheel_movements_by_channel,
                           spare_part_movements_by_channel=sorted_spare_part_movements_by_channel,
                           overall_tire_initial=overall_tire_initial,
                           overall_tire_in=overall_tire_in_period,
                           overall_tire_out=overall_tire_out_period,
                           overall_tire_return=overall_tire_return_period,
                           overall_tire_final=overall_tire_final,
                           overall_wheel_initial=overall_wheel_initial,
                           overall_wheel_in=overall_wheel_in_period,
                           overall_wheel_out=overall_wheel_out_period,
                           overall_wheel_return=overall_wheel_return_period,
                           overall_wheel_final=overall_wheel_final,
                           overall_spare_part_initial=overall_spare_part_initial,
                           overall_spare_part_in=overall_spare_part_in_period,
                           overall_spare_part_out=overall_spare_part_out_period,
                           overall_spare_part_return=overall_spare_part_return_period,
                           overall_spare_part_final=overall_spare_part_final,
                           tires_by_brand_for_summary_report=tires_with_movement,
                           wheels_by_brand_for_summary_report=wheels_with_movement,
                           spare_parts_by_category_and_brand_for_summary_report=spare_parts_with_movement,
                           tire_brand_totals_for_summary_report=tire_brand_totals_for_summary_report,
                           wheel_brand_totals_for_summary_report=wheel_brand_totals_for_summary_report,
                           spare_part_category_totals_for_summary_report=spare_part_category_totals_for_summary_report,
                           current_user=current_user)

# --- Import/Export Routes (assuming these are already in your app.py) ---
@bp.route('/export_import', methods=('GET', 'POST'))
@login_required
def export_import():
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin can import/export
        flash('คุณไม่มีสิทธิ์ในการนำเข้า/ส่งออกข้อมูล', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index'))

    conn = get_db()
    active_tab = request.args.get('tab', 'tires_excel')
    return render_template('export_import.html', active_tab=active_tab, current_user=current_user)

@bp.route('/export_tires_action')
@login_required
def export_tires_action():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการส่งออกข้อมูลยาง', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='tires_excel'))
        
    conn = get_db()
    tires = database.get_all_tires(conn)

    if not tires:
        flash('ไม่มีข้อมูลยางให้ส่งออก', 'warning')
        return redirect(url_for('stock.export_import', tab='tires_excel'))

    data = []
    for tire in tires:
        primary_barcode = ""
        barcodes = database.get_barcodes_for_tire(conn, tire['id'])
        for bc in barcodes:
            if bc['is_primary_barcode']:
                primary_barcode = bc['barcode_string']
                break
        if not primary_barcode and barcodes:
            primary_barcode = barcodes[0]['barcode_string']

        data.append({
            'ยี่ห้อ': tire['brand'],
            'รุ่นยาง': tire['model'],
            'เบอร์ยาง': tire['size'],
            'ปีผลิต': tire['year_of_manufacture'],
            'สต็อก': tire['quantity'],
            'ทุน': tire['cost_sc'], 
            'ทุนล็อต': tire['cost_dunlop'], 
            'ราคาส่ง 1': tire['wholesale_price1'], 
            'ราคาส่งหน้าร้าน': tire['wholesale_price2'], 
            'ราคาขาย': tire['price_per_item'], 
            'Barcode ID (ระบบ)': primary_barcode,
            'ID (ห้ามแก้ไข)': tire['id'],
            # Hidden/System columns (explicitly added here to manage names for import/export)
            'ทุนค้าส่ง 2 (ระบบ)': tire['cost_online'],
            'ID โปรโมชัน (ระบบ)': tire['promotion_id'],
            'ชื่อโปรโมชัน (ระบบ)': tire['promo_name'],
            'ประเภทโปรโมชัน (ระบบ)': tire['promo_type'],
            'ค่าโปรโมชัน Value1 (ระบบ)': tire['promo_value1'],
            'ค่าโปรโมชัน Value2 (ระบบ)': tire['promo_value2'],
            'รายละเอียดโปรโมชัน (ระบบ)': tire['display_promo_description_text'],
            'ราคาโปรโมชันคำนวณ(เส้น) (ระบบ)': tire['display_promo_price_per_item'],
            'ราคาโปรโมชันคำนวณ(4เส้น) (ระบบ)': tire['display_price_for_4'],
        })

    df = pd.DataFrame(data)

    # --- Sort DataFrame before writing to Excel (lowercase for consistent sorting) ---
    df['ยี่ห้อ_sort'] = df['ยี่ห้อ'].str.lower()
    df['รุ่นยาง_sort'] = df['รุ่นยาง'].str.lower()
    df['เบอร์ยาง_sort'] = df['เบอร์ยาง'].str.lower()
    df = df.sort_values(by=['ยี่ห้อ_sort', 'รุ่นยาง_sort', 'เบอร์ยาง_sort', 'ID (ห้ามแก้ไข)'], ascending=True)
    df = df.drop(columns=['ยี่ห้อ_sort', 'รุ่นยาง_sort', 'เบอร์ยาง_sort']) # Drop sort columns

    # Define column order for the main data sheet
    main_sheet_cols = [
        'ยี่ห้อ', 'รุ่นยาง', 'เบอร์ยาง', 'ปีผลิต', 'สต็อก',
        'ทุน', 'ทุนล็อต', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย', 
        'Barcode ID (ระบบ)', 'ID (ห้ามแก้ไข)',
        'ทุนค้าส่ง 2 (ระบบ)',
        'ID โปรโมชัน (ระบบ)', 'ชื่อโปรโมชัน (ระบบ)', 'ประเภทโปรโมชัน (ระบบ)',
        'ค่าโปรโมชัน Value1 (ระบบ)', 'ค่าโปรโมชัน Value2 (ระบบ)',
        'รายละเอียดโปรโมชัน (ระบบ)', 'ราคาโปรโมชันคำนวณ(เส้น) (ระบบ)', 'ราคาโปรโมชันคำนวณ(4เส้น) (ระบบ)',
    ]
    df = df[main_sheet_cols] # Reorder DataFrame columns

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book

    # --- Add an Instructions Sheet ---
    instructions_sheet_name = 'คำแนะนำการใช้งาน'
    instructions_ws = workbook.add_worksheet(instructions_sheet_name)
    instructions_ws.write('A1', 'คำแนะนำการใช้งานไฟล์นำเข้า/ส่งออกข้อมูลยาง', workbook.add_format({'bold': True, 'font_size': 14}))
    instructions_ws.write('A3', 'วัตถุประสงค์:', workbook.add_format({'bold': True}))
    instructions_ws.write('A4', 'ไฟล์นี้ใช้สำหรับ Export ข้อมูลสต็อกยางปัจจุบัน และสามารถใช้เป็นแม่แบบเพื่อนำเข้าข้อมูลใหม่หรือแก้ไขข้อมูลที่มีอยู่ได้', workbook.add_format({'text_wrap': True}))
    instructions_ws.write('A6', 'ข้อควรระวัง:', workbook.add_format({'bold': True, 'font_color': 'red'}))
    instructions_ws.write('A7', '1. ห้าม! เปลี่ยนชื่อชีท "Tires Data" และห้าม! ลบ/ย้าย/เปลี่ยนชื่อคอลัมน์ในชีท "Tires Data"', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A8', '2. ข้อมูลในคอลัมน์ที่มีคำว่า "(ห้ามแก้ไข)" หรือ "(ระบบ)" เป็นข้อมูลที่สร้าง/คำนวณโดยระบบ ไม่ควรแก้ไข', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A9', '3. การแก้ไขค่าในคอลัมน์ "สต็อก" จะถูกบันทึกเป็นการเคลื่อนไหว (รับเข้า/จ่ายออก)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A10', '4. หากต้องการเพิ่มสินค้าใหม่ ไม่ต้องกรอก "ID (ห้ามแก้ไข)"', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A11', '5. ตรวจสอบประเภทข้อมูลให้ถูกต้อง (ตัวเลข, ข้อความ)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A12', '6. สามารถเปลี่ยนชื่อไฟล์ได้' , workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.set_column('A:A', 80) # Adjust width for instructions

    # --- Write data to the main sheet with blank rows between brands ---
    data_sheet_name = 'Tires Data'
    worksheet = workbook.add_worksheet(data_sheet_name) # Create worksheet manually

    # Define formats
    header_format = workbook.add_format({
        'bold': True, 'text_wrap': True, 'valign': 'vcenter',
        'fg_color': '#D7E4BC', 'border': 1, 'align': 'center'
    })
    read_only_header_format = workbook.add_format({ # Format for headers of columns not meant for import
        'bold': True, 'text_wrap': True, 'valign': 'vcenter',
        'fg_color': '#D9D9D9', 'border': 1, 'font_color': '#5C5C5C', 'align': 'center'
    })
    read_only_cell_format = workbook.add_format({ # Format for cells in columns not meant for import
        'font_color': '#808080', 'italic': True, 'align': 'center', 'valign': 'vcenter'
    })
    integer_format = workbook.add_format({'num_format': '#,##0', 'align': 'center'})
    decimal_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
    text_center_format = workbook.add_format({'align': 'center'})
    text_left_format = workbook.add_format({'align': 'left'})
    
    # Write headers to the main sheet
    for col_num, value in enumerate(df.columns.values):
        is_read_only_col = '(ห้ามแก้ไข)' in value or '(ระบบ)' in value
        current_header_format = read_only_header_format if is_read_only_col else header_format
        worksheet.write(0, col_num, value, current_header_format)

        # Set initial column widths based on header and max data length
        max_len = max(df[value].astype(str).apply(len).max(), len(value)) + 2
        
        if value == 'ยี่ห้อ':
            worksheet.set_column(col_num, col_num, max(max_len, 15), text_left_format)
        elif value == 'รุ่นยาง':
            worksheet.set_column(col_num, col_num, max(max_len, 20), text_left_format)
        elif value == 'เบอร์ยาง':
            worksheet.set_column(col_num, col_num, max(max_len, 15), text_center_format)
        elif value == 'สต็อก':
            worksheet.set_column(col_num, col_num, max(max_len, 10), integer_format)
        elif value == 'ปีผลิต':
            worksheet.set_column(col_num, col_num, max(max_len, 8), text_center_format)
        elif value == 'ราคาขาย': 
            worksheet.set_column(col_num, col_num, max(max_len, 12), decimal_format)
        elif value == 'Barcode ID (ระบบ)': 
            worksheet.set_column(col_num, col_num, max(max_len, 20), read_only_cell_format, {'hidden': True})
        elif value == 'ทุนค้าส่ง 2 (ระบบ)': 
            worksheet.set_column(col_num, col_num, max(max_len, 15), read_only_cell_format, {'hidden': True}) # HIDDEN
        elif value in ['ทุน', 'ทุนล็อต', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย']: 
            worksheet.set_column(col_num, col_num, max(max_len, 12), decimal_format)
        elif is_read_only_col: 
            worksheet.set_column(col_num, col_num, max(max_len, 15), read_only_cell_format)
            if value in ['ID (ห้ามแก้ไข)', 'ID โปรโมชัน (ระบบ)', 'ชื่อโปรโมชัน (ระบบ)', 'ประเภทโปรโมชัน (ระบบ)', 'ค่าโปรโมชัน Value1 (ระบบ)', 'ค่าโปรโมชัน Value2 (ระบบ)', 'รายละเอียดโปรโมชัน (ระบบ)', 'ราคาโปรโมชันคำนวณ(เส้น) (ระบบ)', 'ราคาโปรโมชันคำนวณ(4เส้น) (ระบบ)']:
                worksheet.set_column(col_num, col_num, None, None, {'hidden': True})
        else:
            worksheet.set_column(col_num, col_num, max_len)

    # Write data rows with blank rows between brands
    current_row = 1
    last_brand = None
    
    for index, row_data in df.iterrows():
        current_brand = row_data['ยี่ห้อ']
        if last_brand is not None and current_brand != last_brand:
            current_row += 1 # Add a blank row between brands

        for col_num, col_name in enumerate(df.columns.values):
            cell_value = row_data[col_name]
            cell_format = None

            # Determine format based on column name and whether it's a read-only column
            is_read_only_col = '(ห้ามแก้ไข)' in col_name or '(ระบบ)' in col_name
            
            if is_read_only_col:
                cell_format = read_only_cell_format
            elif col_name == 'สต็อก':
                cell_format = integer_format
            elif col_name in ['ทุน', 'ทุนล็อต', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย']:
                cell_format = decimal_format
            elif col_name == 'ยี่ห้อ':
                cell_format = text_left_format
            elif col_name == 'รุ่นยาง':
                cell_format = text_left_format
            elif col_name in ['เบอร์ยาง', 'ปีผลิต']:
                cell_format = text_center_format
            
            # --- Handle NaN values by writing None instead of np.nan ---
            if pd.isna(cell_value):
                worksheet.write(current_row, col_num, None, cell_format) # Write None to produce a blank cell
            else:
                worksheet.write(current_row, col_num, cell_value, cell_format)
        current_row += 1
        last_brand = current_brand

    # --- Add Freeze Panes ---
    worksheet.freeze_panes(1, 0) # Freeze the first row (headers)


    # --- REMOVED: Create Summary by Brand Sheet (for Tires) ---


    writer.close()
    output.seek(0)

    return send_file(output, download_name='tire_stock_template.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@bp.route('/import_tires_action', methods=['POST'])
@login_required
def import_tires_action():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการนำเข้าข้อมูลยาง', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='tires_excel'))
        
    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='tires_excel'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='tires_excel'))
    
    if file and allowed_excel_file(file.filename):
        try:
            xls = pd.ExcelFile(file)
            if 'Tires Data' not in xls.sheet_names:
                flash('ไม่พบชีทชื่อ "Tires Data" ในไฟล์. โปรดตรวจสอบว่าคุณใช้ไฟล์แม่แบบที่ถูกต้อง', 'danger')
                conn.rollback()
                return redirect(url_for('stock.export_import', tab='tires_excel'))
            
            df = xls.parse('Tires Data', dtype={'Barcode ID (ระบบ)': str})
            
            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            expected_tire_cols = [
                'ยี่ห้อ', 'รุ่นยาง', 'เบอร์ยาง', 'ปีผลิต', 'สต็อก',
                'ทุน', 'ทุนล็อต', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย' 
            ]
            
            if not all(col in df.columns for col in expected_tire_cols):
                missing_cols = [col for col in expected_tire_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                conn.rollback()
                return redirect(url_for('stock.export_import', tab='tires_excel'))

            for index, row in df.iterrows():
                if pd.isna(row.get('ยี่ห้อ')) and pd.isna(row.get('รุ่นยาง')) and pd.isna(row.get('เบอร์ยาง')) and pd.isna(row.get('สต็อก')):
                    error_rows.append(f"แถวที่ {index + 2}: ข้อมูลหลัก (ยี่ห้อ, รุ่นยาง, เบอร์ยาง, สต็อก) ว่างเปล่า. แถวถูกข้าม.")
                    continue

                try:
                    tire_id_from_excel = int(row.get('ID (ห้ามแก้ไข)')) if pd.notna(row.get('ID (ห้ามแก้ไข)')) else None
                    barcode_id_from_excel = str(row.get('Barcode ID (ระบบ)', '')).strip()
                    promotion_id_from_excel_raw = row.get('ID โปรโมชัน (ระบบ)')

                    barcode_id_to_save = None
                    if barcode_id_from_excel and barcode_id_from_excel.lower() not in ['none', 'nan']:
                        barcode_id_to_save = barcode_id_from_excel

                    brand = str(row.get('ยี่ห้อ', '')).strip().lower()
                    model = str(row.get('รุ่นยาง', '')).strip().lower()
                    size = str(row.get('เบอร์ยาง', '')).strip()
                    year_of_manufacture_raw = row.get('ปีผลิต')
                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    cost_sc_raw = row.get('ทุน')
                    cost_dunlop_raw = row.get('ทุนล็อต')
                    cost_online_raw = row.get('ทุนค้าส่ง 2 (ระบบ)')
                    wholesale_price1_raw = row.get('ราคาส่ง 1')
                    wholesale_price2_raw = row.get('ราคาส่งหน้าร้าน')
                    price_per_item_raw = row.get('ราคาขาย')

                    if not brand or not model or not size:
                        raise ValueError("ข้อมูล 'ยี่ห้อ', 'รุ่นยาง', หรือ 'เบอร์ยาง' ไม่สามารถเว้นว่างได้")
                    if pd.isna(price_per_item_raw):
                         raise ValueError("ข้อมูล 'ราคาขาย' ไม่สามารถเว้นว่างได้")

                    try:
                        price_per_item = float(price_per_item_raw)
                        cost_sc = float(cost_sc_raw) if pd.notna(cost_sc_raw) else None
                        cost_dunlop = float(cost_dunlop_raw) if pd.notna(cost_dunlop_raw) else None
                        cost_online = float(cost_online_raw) if pd.notna(cost_online_raw) else None
                        wholesale_price1 = float(wholesale_price1_raw) if pd.notna(wholesale_price1_raw) else None
                        wholesale_price2 = float(wholesale_price2_raw) if pd.notna(wholesale_price2_raw) else None
                    except ValueError as ve:
                        raise ValueError(f"ข้อมูลตัวเลขไม่ถูกต้องในคอลัมน์ราคาหรือทุน: {ve}")

                    year_of_manufacture = None
                    if pd.notna(year_of_manufacture_raw):
                        try:
                            year_of_manufacture = int(year_of_manufacture_raw)
                        except ValueError:
                            year_of_manufacture = str(year_of_manufacture_raw).strip()
                            if year_of_manufacture.lower() == 'nan':
                                year_of_manufacture = None

                    promotion_id_db = int(promotion_id_from_excel_raw) if pd.notna(promotion_id_from_excel_raw) else None
                    
                    cursor = conn.cursor()
                    existing_tire = None
                    if tire_id_from_excel:
                        existing_tire = database.get_tire(conn, tire_id_from_excel)

                    if not existing_tire and barcode_id_to_save:
                        existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_id_to_save)
                        if existing_tire_id_by_barcode:
                            conn.rollback()
                            existing_tire = database.get_tire(conn, existing_tire_id_by_barcode)
                            if existing_tire and existing_tire['id'] != tire_id_from_excel and tire_id_from_excel is not None:
                                raise ValueError(f"ID ({tire_id_from_excel}) ใน Excel ไม่ตรงกับ ID ที่พบจาก Barcode ({existing_tire_id_by_barcode}). กรุณาแก้ไข ID ใน Excel หรือลบออก.")

                        existing_wheel_id_by_barcode = database.get_wheel_id_by_barcode(conn, barcode_id_to_save)
                        if existing_wheel_id_by_barcode:
                            conn.rollback()
                            raise ValueError(f"Barcode ID '{barcode_id_to_save}' ซ้ำกับล้อแม็ก ID {existing_wheel_id_by_barcode}. Barcode ID ต้องไม่ซ้ำกันข้ามประเภทสินค้า.")

                    if not existing_tire:
                        if "psycopg2" in str(type(conn)):
                            cursor.execute("SELECT id, brand, model, size, quantity, cost_sc FROM tires WHERE brand = %s AND model = %s AND size = %s", (brand, model, size))
                        else:
                            cursor.execute("SELECT id, brand, model, size, quantity, cost_sc FROM tires WHERE brand = ? AND model = ? AND size = ?", (brand, model, size))
                        
                        found_tire_data = cursor.fetchone()
                        if found_tire_data:
                            existing_tire = dict(found_tire_data)
                            if existing_tire and existing_tire['id'] != tire_id_from_excel and tire_id_from_excel is not None:
                                raise ValueError(f"ID ({tire_id_from_excel}) ใน Excel ไม่ตรงกับสินค้าที่มีอยู่แล้วด้วย ยี่ห้อ/รุ่น/เบอร์ ({existing_tire['id']}). กรุณาแก้ไข ID ใน Excel หรือลบออก.")

                    if existing_tire:
                        tire_id = existing_tire['id']
                        
                        # --- START: ส่วนที่เพิ่มเข้ามาเพื่อบันทึกประวัติ ---
                        old_cost_sc = existing_tire.get('cost_sc')
                        
                        if old_cost_sc != cost_sc:
                            database.add_tire_cost_history(
                                conn=conn,
                                tire_id=tire_id,
                                old_cost=old_cost_sc,
                                new_cost=cost_sc,
                                user_id=current_user.id,
                                notes="แก้ไขผ่านการนำเข้า Excel"
                            )
                        # --- END: ส่วนที่เพิ่มเข้ามา ---
                        
                        if barcode_id_to_save and not database.get_tire_id_by_barcode(conn, barcode_id_to_save):
                             database.add_tire_barcode(conn, tire_id, barcode_id_to_save, is_primary=False)
                        
                        database.update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item,
                                                    promotion_id_db, year_of_manufacture)
                        
                        old_quantity = existing_tire['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_tire_movement(conn, tire_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                        updated_count += 1
                        
                    else: # New tire
                        new_tire_id = database.add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item,
                                                                promotion_id_db, year_of_manufacture)
                        if barcode_id_to_save:
                            database.add_tire_barcode(conn, new_tire_id, barcode_id_to_save, is_primary=True)
                        database.add_tire_movement(conn, new_tire_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None, user_id=current_user.id)
                        imported_count += 1
                
                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")
            
            conn.commit()
            cache.delete_memoized(get_all_tires_list_cached)
            cache.delete_memoized(get_cached_tire_brands)
            cache.delete_memoized(get_cached_wholesale_summary)
            cache.delete_memoized(get_cached_unread_notification_count)

            message = f'นำเข้าข้อมูลยางสำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:5])}{"..." if len(error_rows) > 5 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')

            return redirect(url_for('stock.export_import', tab='tires_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดร้ายแรงในการนำเข้าไฟล์ Excel ของยาง: {e}', 'danger')
            conn.rollback()
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('stock.export_import', tab='tires_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='tires_excel'))


@bp.route('/export_wheels_action')
@login_required
def export_wheels_action():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการส่งออกข้อมูลแม็ก', 'danger')
        return redirect(url_for('stock.export_import', tab='wheels_excel'))
        
    conn = get_db()
    wheels = database.get_all_wheels(conn)
    
    if not wheels:
        flash('ไม่มีข้อมูลแม็กให้ส่งออก', 'warning')
        return redirect(url_for('stock.export_import', tab='wheels_excel'))

    data = []
    for wheel in wheels:
        primary_barcode = ""
        barcodes = database.get_barcodes_for_wheel(conn, wheel['id'])
        for bc in barcodes:
            if bc['is_primary_barcode']:
                primary_barcode = bc['barcode_string']
                break
        if not primary_barcode and barcodes:
            primary_barcode = barcodes[0]['barcode_string']

        data.append({
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
            'ราคาส่ง 1': wheel['wholesale_price1'], 
            'ราคาส่งหน้าร้าน': wheel['wholesale_price2'], 
            'ราคาขาย': wheel['retail_price'], 
            'Barcode ID (ระบบ)': primary_barcode, 
            'ID (ห้ามแก้ไข)': wheel['id'], 
            'ไฟล์รูปภาพ (URL ระบบ)': wheel['image_filename'], 
        })

    df = pd.DataFrame(data)

    # --- Sort DataFrame before writing to Excel ---
    df['ยี่ห้อ'] = df['ยี่ห้อ'].str.lower()
    df['ลาย'] = df['ลาย'].str.lower()
    df = df.sort_values(by=['ยี่ห้อ', 'ลาย', 'ขอบ', 'ID (ห้ามแก้ไข)'], ascending=True)

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book 

    # --- Add an Instructions Sheet ---
    instructions_sheet_name = 'คำแนะนำการใช้งาน'
    instructions_ws = workbook.add_worksheet(instructions_sheet_name) 
    instructions_ws.write('A1', 'คำแนะนำการใช้งานไฟล์นำเข้า/ส่งออกข้อมูลแม็ก', workbook.add_format({'bold': True, 'font_size': 14}))
    instructions_ws.write('A3', 'วัตถุประสงค์:', workbook.add_format({'bold': True}))
    instructions_ws.write('A4', 'ไฟล์นี้ใช้สำหรับ Export ข้อมูลสต็อกแม็กปัจจุบัน และสามารถใช้เป็นแม่แบบเพื่อนำเข้าข้อมูลใหม่หรือแก้ไขข้อมูลที่มีอยู่ได้', workbook.add_format({'text_wrap': True}))
    instructions_ws.write('A6', 'ข้อควรระวัง:', workbook.add_format({'bold': True, 'font_color': 'red'}))
    instructions_ws.write('A7', '1. ห้าม! เปลี่ยนชื่อชีท "Wheels Data" และห้าม! ลบ/ย้าย/เปลี่ยนชื่อคอลัมน์ในชีท "Wheels Data"', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A8', '2. ข้อมูลในคอลัมน์ที่มีคำว่า "(ห้ามแก้ไข)" หรือ "(ระบบ)" เป็นข้อมูลที่สร้าง/คำนวณโดยระบบ ไม่ควรแก้ไข', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A9', '3. การแก้ไขค่าในคอลัมน์ "สต็อก" จะถูกบันทึกเป็นการเคลื่อนไหว (รับเข้า/จ่ายออก)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A10', '4. หากต้องการเพิ่มสินค้าใหม่ ไม่ต้องกรอก "ID (ห้ามแก้ไข)"', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A11', '5. "ไฟล์รูปภาพ (URL ระบบ)" คือ URL รูปภาพที่ระบบใช้ ไม่ควรแก้ไขโดยตรง หากต้องการเปลี่ยนรูป ให้ใช้ฟังก์ชันอัปโหลดในระบบ', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A12', '6. ตรวจสอบประเภทข้อมูลให้ถูกต้อง (ตัวเลข, ข้อความ)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.set_column('A:A', 80) # Adjust width for instructions

    # Write data to the main sheet
    data_sheet_name = 'Wheels Data'
    worksheet = workbook.add_worksheet(data_sheet_name) # Create worksheet manually

    # Define formats
    header_format = workbook.add_format({
        'bold': True,
        'text_wrap': True,
        'valign': 'vcenter',
        'fg_color': '#D7E4BC',
        'border': 1,
        'align': 'center'
    })
    read_only_header_format = workbook.add_format({
        'bold': True,
        'text_wrap': True,
        'valign': 'vcenter',
        'fg_color': '#D9D9D9',
        'border': 1,
        'font_color': '#5C5C5C',
        'align': 'center'
    })
    read_only_cell_format = workbook.add_format({
        'font_color': '#808080',
        'italic': True,
        'align': 'center',
        'valign': 'vcenter'
    })

    # Number formats
    integer_format = workbook.add_format({'num_format': '#,##0', 'align': 'center'})
    decimal_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
    text_center_format = workbook.add_format({'align': 'center'})
    text_left_format = workbook.add_format({'align': 'left'})
    
    # Apply header format and set column widths for main sheet
    for col_num, value in enumerate(df.columns.values):
        is_read_only_col = '(ห้ามแก้ไข)' in value or '(ระบบ)' in value or '(URL ระบบ)' in value
        current_header_format = read_only_header_format if is_read_only_col else header_format
        worksheet.write(0, col_num, value, current_header_format)

        max_len = max(df[value].astype(str).apply(len).max(), len(value)) + 2

        if value == 'ยี่ห้อ':
            worksheet.set_column(col_num, col_num, max(max_len, 15), text_left_format)
        elif value == 'ลาย':
            worksheet.set_column(col_num, col_num, max(max_len, 20), text_left_format)
        elif value in ['ขอบ', 'กว้าง', 'ET', 'รู']:
            worksheet.set_column(col_num, col_num, max(max_len, 8), text_center_format)
        elif value == 'สี':
            worksheet.set_column(col_num, col_num, max(max_len, 15), text_center_format)
        elif value == 'สต็อก':
            worksheet.set_column(col_num, col_num, max(max_len, 10), integer_format)
        elif value == 'Barcode ID (ระบบ)': 
            worksheet.set_column(col_num, col_num, max(max_len, 20), read_only_cell_format, {'hidden': True})
        elif value in ['ทุน', 'ทุน Online', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย']: 
            worksheet.set_column(col_num, col_num, max(max_len, 12), decimal_format)
        elif is_read_only_col:
            worksheet.set_column(col_num, col_num, max(max_len, 25), read_only_cell_format)
            if value in ['ID (ห้ามแก้ไข)', 'ไฟล์รูปภาพ (URL ระบบ)']:
                worksheet.set_column(col_num, col_num, None, None, {'hidden': True})
        else:
            worksheet.set_column(col_num, col_num, max_len)
    
    # Write data rows with blank rows between brands for Wheels
    current_row = 1
    last_brand = None
    
    for index, row_data in df.iterrows():
        current_brand = row_data['ยี่ห้อ']
        if last_brand is not None and current_brand != last_brand:
            current_row += 1 # Add a blank row between brands

        for col_num, col_name in enumerate(df.columns.values):
            cell_value = row_data[col_name]
            cell_format = None

            is_read_only_col = '(ห้ามแก้ไข)' in col_name or '(ระบบ)' in col_name or '(URL ระบบ)' in col_name
            
            if is_read_only_col:
                cell_format = read_only_cell_format
            elif col_name == 'สต็อก':
                cell_format = integer_format
            elif col_name in ['ทุน', 'ทุน Online', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย']:
                cell_format = decimal_format
            elif col_name == 'ยี่ห้อ':
                cell_format = text_left_format
            elif col_name == 'ลาย':
                cell_format = text_left_format
            elif col_name in ['ขอบ', 'กว้าง', 'ET', 'รู', 'สี']:
                cell_format = text_center_format
            
            # --- Handle NaN values by writing None instead of np.nan ---
            if pd.isna(cell_value):
                worksheet.write(current_row, col_num, None, cell_format) # Write None to produce a blank cell
            else:
                worksheet.write(current_row, col_num, cell_value, cell_format)
        current_row += 1
        last_brand = current_brand

    # --- Add Freeze Panes ---
    worksheet.freeze_panes(1, 0) # Freeze the first row (headers)

    # --- REMOVED: Create Summary by Brand Sheet (for Wheels) ---
    # (Removed as per user request)

    writer.close()
    output.seek(0)

    return send_file(output, download_name='wheel_stock_template.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@bp.route('/import_wheels_action', methods=['POST'])
@login_required
def import_wheels_action():
    # Check permission directly inside the route function
    if not current_user.can_edit(): # Admin or Editor
        flash('คุณไม่มีสิทธิ์ในการนำเข้าข้อมูลแม็ก', 'danger')
        return redirect(url_for('stock.export_import', tab='wheels_excel'))
        
    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='wheels_excel'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='wheels_excel'))
    
    if file and allowed_excel_file(file.filename):
        try:
            xls = pd.ExcelFile(file)
            if 'Wheels Data' not in xls.sheet_names:
                flash('ไม่พบชีทชื่อ "Wheels Data" ในไฟล์. โปรดตรวจสอบว่าคุณใช้ไฟล์แม่แบบที่ถูกต้อง', 'danger')
                conn.rollback()
                return redirect(url_for('stock.export_import', tab='wheels_excel'))
            
            # Use original 'Barcode ID (ระบบ)' for parsing dtype (as it's the internal name)
            df = xls.parse('Wheels Data', dtype={'Barcode ID (ระบบ)': str})
            
            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            # UPDATED: Expected column names now match the export format
            expected_wheel_cols = [
                'ยี่ห้อ', 'ลาย', 'ขอบ', 'รู', 'กว้าง', 'ET', 'สี', 'สต็อก',
                'ทุน', 'ทุน Online', 'ราคาส่ง 1', 'ราคาส่งหน้าร้าน', 'ราคาขาย' 
            ]
            
            # Check if all required columns are present
            if not all(col in df.columns for col in expected_wheel_cols):
                missing_cols = [col for col in expected_wheel_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                conn.rollback()
                return redirect(url_for('stock.export_import', tab='wheels_excel'))

            for index, row in df.iterrows():
                # --- NEW: Skip blank rows ---
                # Check if essential columns are NaN or empty strings
                if pd.isna(row.get('ยี่ห้อ')) and \
                   pd.isna(row.get('ลาย')) and \
                   pd.isna(row.get('ขอบ')) and \
                   pd.isna(row.get('สต็อก')):
                    error_rows.append(f"แถวที่ {index + 2}: ข้อมูลหลัก (ยี่ห้อ, ลาย, ขอบ, สต็อก) ว่างเปล่า. แถวถูกข้าม.")
                    continue # Skip this row

                try:
                    # Retrieve optional/system columns with their new names
                    wheel_id_from_excel = int(row.get('ID (ห้ามแก้ไข)')) if pd.notna(row.get('ID (ห้ามแก้ไข)')) else None
                    barcode_id_from_excel = str(row.get('Barcode ID (ระบบ)', '')).strip()

                    # Clean barcode string
                    barcode_id_to_save = None
                    if barcode_id_from_excel and barcode_id_from_excel.lower() not in ['none', 'nan']:
                        barcode_id_to_save = barcode_id_from_excel

                    # Required fields (using their new names from export)
                    brand = str(row.get('ยี่ห้อ', '')).strip().lower()
                    model = str(row.get('ลาย', '')).strip().lower()
                    diameter_raw = row.get('ขอบ')
                    pcd = str(row.get('รู', '')).strip()
                    width_raw = row.get('กว้าง')
                    et_raw = row.get('ET')
                    color = str(row.get('สี', '')).strip()
                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    cost_raw = row.get('ทุน')
                    cost_online_raw = row.get('ทุน Online')
                    wholesale_price1_raw = row.get('ราคาส่ง 1') 
                    wholesale_price2_raw = row.get('ราคาส่งหน้าร้าน') 
                    retail_price_raw = row.get('ราคาขาย') 


                    # Validation for required fields for new/update
                    if not brand or not model or not pcd:
                            raise ValueError("ข้อมูล 'ยี่ห้อ', 'ลาย', หรือ 'รู' ไม่สามารถเว้นว่างได้")
                    if pd.isna(diameter_raw) or pd.isna(width_raw) or pd.isna(retail_price_raw):
                        raise ValueError("ข้อมูล 'ขอบ', 'กว้าง', หรือ 'ราคาขาย' ไม่สามารถเว้นว่างได้")


                    # Type conversions
                    try:
                        diameter = float(diameter_raw)
                        width = float(width_raw)
                        retail_price = float(retail_price_raw)
                        cost = float(cost_raw) if pd.notna(cost_raw) else None
                        et = int(et_raw) if pd.notna(et_raw) else None
                        cost_online = float(cost_online_raw) if pd.notna(cost_online_raw) else None
                        wholesale_price1 = float(wholesale_price1_raw) if pd.notna(wholesale_price1_raw) else None 
                        wholesale_price2 = float(wholesale_price2_raw) if pd.notna(wholesale_price2_raw) else None 
                    except ValueError as ve:
                        raise ValueError(f"ข้อมูลตัวเลขไม่ถูกต้องในคอลัมน์ราคา, ทุน, หรือขนาด: {ve}")

                    cursor = conn.cursor()

                    existing_wheel = None
                    if wheel_id_from_excel:
                        existing_wheel = database.get_wheel(conn, wheel_id_from_excel)
                        
                    # If not found by ID or no ID provided, try to find by Barcode ID
                    if not existing_wheel and barcode_id_to_save:
                        existing_wheel_id_by_barcode = database.get_wheel_id_by_barcode(conn, barcode_id_to_save)
                        if existing_wheel_id_by_barcode:
                            conn.rollback()
                            existing_wheel = database.get_wheel(conn, existing_wheel_id_by_barcode)
                            if existing_wheel and existing_wheel['id'] != wheel_id_from_excel and wheel_id_from_excel is not None:
                                raise ValueError(f"ID ({wheel_id_from_excel}) ใน Excel ไม่ตรงกับ ID ที่พบจาก Barcode ({existing_wheel_id_by_barcode}). กรุณาแก้ไข ID ใน Excel หรือลบออก.")

                        existing_tire_id_by_barcode = database.get_tire_id_by_barcode(conn, barcode_id_to_save)
                        if existing_tire_id_by_barcode:
                            conn.rollback()
                            raise ValueError(f"Barcode ID '{barcode_id_to_save}' ซ้ำกับยาง ID {existing_tire_id_by_barcode}. Barcode ID ต้องไม่ซ้ำกันข้ามประเภทสินค้า.")

                    # If still not found by ID or Barcode, try to find by Brand/Model/Diameter/PCD/Width
                    if not existing_wheel:
                        if "psycopg2" in str(type(conn)):
                            cursor.execute("SELECT id, brand, model, diameter, pcd, width, quantity FROM wheels WHERE brand = %s AND model = %s AND diameter = %s AND pcd = %s AND width = %s", 
                                        (brand, model, diameter, pcd, width))
                        else:
                            cursor.execute("SELECT id, brand, model, diameter, pcd, width, quantity FROM wheels WHERE brand = ? AND model = ? AND diameter = ? AND pcd = ? AND width = ?", 
                                        (brand, model, diameter, pcd, width))
                        
                        found_wheel_data = cursor.fetchone()
                        if found_wheel_data:
                            existing_wheel = dict(found_wheel_data)
                            if existing_wheel and existing_wheel['id'] != wheel_id_from_excel and wheel_id_from_excel is not None:
                                raise ValueError(f"ID ({wheel_id_from_excel}) ใน Excel ไม่ตรงกับสินค้าที่มีอยู่แล้วด้วย ยี่ห้อ/ลาย/ขอบ/รู/กว้าง ({existing_wheel['id']}). กรุณาแก้ไข ID ใน Excel หรือลบออก.")


                    if existing_wheel:
                        wheel_id = existing_wheel['id']
                        
                        # Add or update barcode if provided and not already linked
                        if barcode_id_to_save and not database.get_wheel_id_by_barcode(conn, barcode_id_to_save):
                             database.add_wheel_barcode(conn, wheel_id, barcode_id_to_save, is_primary=False)
                        
                        database.update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        
                        old_quantity = existing_wheel['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_wheel_movement(conn, wheel_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                        updated_count += 1
                        
                    else: # New wheel
                        new_wheel_id = database.add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url)
                        if barcode_id_to_save:
                            database.add_wheel_barcode(conn, new_wheel_id, barcode_id_to_save, is_primary=True)
                        database.add_wheel_movement(conn, new_wheel_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None, user_id=current_user.id)
                        imported_count += 1
                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")
            
            conn.commit()
            cache.delete_memoized(get_all_wheels_list_cached)
            cache.delete_memoized(get_cached_wheel_brands)
            # Potentially clear wholesale_summary_cache and unread_notification_count if stock movements from import add notifications or affect wholesale
            # (Assuming add_wheel_movement adds notifications, and wholesale_summary is tied to movements)
            cache.delete_memoized(get_cached_wholesale_summary)
            cache.delete_memoized(get_cached_unread_notification_count)
            
            message = f'นำเข้าข้อมูลแม็กสำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:5])}{"..." if len(error_rows) > 5 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')
            
            return redirect(url_for('stock.export_import', tab='wheels_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดร้ายแรงในการนำเข้าไฟล์ Excel ของแม็ก: {e}', 'danger')
            conn.rollback()
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('stock.export_import', tab='wheels_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='wheels_excel'))

@bp.route('/export_spare_parts_action')
@login_required
def export_spare_parts_action():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการส่งออกข้อมูลอะไหล่', 'danger')
        return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

    conn = get_db()
    spare_parts = database.get_all_spare_parts(conn)

    if not spare_parts:
        flash('ไม่มีข้อมูลอะไหล่ให้ส่งออก', 'warning')
        return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

    data = []
    for part in spare_parts:
        primary_barcode = ""
        barcodes = database.get_barcodes_for_spare_part(conn, part['id'])
        for bc in barcodes:
            if bc['is_primary_barcode']:
                primary_barcode = bc['barcode_string']
                break
        if not primary_barcode and barcodes: # Fallback to first barcode if no primary is set
            primary_barcode = barcodes[0]['barcode_string']

        data.append({
            'ชื่ออะไหล่': part['name'],
            'Part Number': part['part_number'],
            'ยี่ห้อ': part['brand'],
            'หมวดหมู่': part['category_name'], # NEW: Export category name
            'คำอธิบาย': part['description'],
            'สต็อก': part['quantity'],
            'ทุน': part['cost'],
            'ราคาขายปลีก': part['retail_price'],
            'ราคาส่ง 1': part['wholesale_price1'],
            'ราคาส่ง 2': part['wholesale_price2'],
            'ทุน Online': part['cost_online'],
            'Barcode ID (ระบบ)': primary_barcode,
            'ID (ห้ามแก้ไข)': part['id'],
            'ID หมวดหมู่ (ระบบ)': part['category_id'], # NEW: Export category_id
            'ไฟล์รูปภาพ (URL ระบบ)': part['image_filename'],
        })

    df = pd.DataFrame(data)

    # Sort DataFrame before writing to Excel
    df['หมวดหมู่_sort'] = df['หมวดหมู่'].str.lower()
    df['ยี่ห้อ_sort'] = df['ยี่ห้อ'].str.lower()
    df['ชื่ออะไหล่_sort'] = df['ชื่ออะไหล่'].str.lower()
    df = df.sort_values(by=['หมวดหมู่_sort', 'ยี่ห้อ_sort', 'ชื่ออะไหล่_sort', 'ID (ห้ามแก้ไข)'], ascending=True)
    df = df.drop(columns=['หมวดหมู่_sort', 'ยี่ห้อ_sort', 'ชื่ออะไหล่_sort'])

    # Define column order for the main data sheet
    main_sheet_cols = [
        'ชื่ออะไหล่', 'Part Number', 'ยี่ห้อ', 'หมวดหมู่', 'คำอธิบาย', 'สต็อก',
        'ทุน', 'ราคาขายปลีก', 'ราคาส่ง 1', 'ราคาส่ง 2', 'ทุน Online',
        'Barcode ID (ระบบ)', 'ID (ห้ามแก้ไข)', 'ID หมวดหมู่ (ระบบ)', 'ไฟล์รูปภาพ (URL ระบบ)',
    ]
    df = df[main_sheet_cols]

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book

    # --- Add an Instructions Sheet ---
    instructions_sheet_name = 'คำแนะนำการใช้งาน'
    instructions_ws = workbook.add_worksheet(instructions_sheet_name)
    instructions_ws.write('A1', 'คำแนะนำการใช้งานไฟล์นำเข้า/ส่งออกข้อมูลอะไหล่', workbook.add_format({'bold': True, 'font_size': 14}))
    instructions_ws.write('A3', 'วัตถุประสงค์:', workbook.add_format({'bold': True}))
    instructions_ws.write('A4', 'ไฟล์นี้ใช้สำหรับ Export ข้อมูลสต็อกอะไหล่ปัจจุบัน และสามารถใช้เป็นแม่แบบเพื่อนำเข้าข้อมูลใหม่หรือแก้ไขข้อมูลที่มีอยู่ได้', workbook.add_format({'text_wrap': True}))
    instructions_ws.write('A6', 'ข้อควรระวัง:', workbook.add_format({'bold': True, 'font_color': 'red'}))
    instructions_ws.write('A7', '1. ห้าม! เปลี่ยนชื่อชีท "Spare Parts Data" และห้าม! ลบ/ย้าย/เปลี่ยนชื่อคอลัมน์ในชีท "Spare Parts Data"', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A8', '2. ข้อมูลในคอลัมน์ที่มีคำว่า "(ห้ามแก้ไข)" หรือ "(ระบบ)" เป็นข้อมูลที่สร้าง/คำนวณโดยระบบ ไม่ควรแก้ไข', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A9', '3. การแก้ไขค่าในคอลัมน์ "สต็อก" จะถูกบันทึกเป็นการเคลื่อนไหว (รับเข้า/จ่ายออก)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A10', '4. หากต้องการเพิ่มสินค้าใหม่ ไม่ต้องกรอก "ID (ห้ามแก้ไข)"', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A11', '5. "ไฟล์รูปภาพ (URL ระบบ)" คือ URL รูปภาพที่ระบบใช้ ไม่ควรแก้ไขโดยตรง หากต้องการเปลี่ยนรูป ให้ใช้ฟังก์ชันอัปโหลดในระบบ', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A12', '6. "หมวดหมู่" ต้องตรงกับหมวดหมู่ที่มีอยู่ในระบบ (สร้าง/จัดการได้ที่หน้าจัดการหมวดหมู่)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.write('A13', '7. ตรวจสอบประเภทข้อมูลให้ถูกต้อง (ตัวเลข, ข้อความ)', workbook.add_format({'font_color': 'red', 'text_wrap': True}))
    instructions_ws.set_column('A:A', 80)

    # Write data to the main sheet
    data_sheet_name = 'Spare Parts Data'
    worksheet = workbook.add_worksheet(data_sheet_name)

    # Define formats
    header_format = workbook.add_format({
        'bold': True, 'text_wrap': True, 'valign': 'vcenter',
        'fg_color': '#D7E4BC', 'border': 1, 'align': 'center'
    })
    read_only_header_format = workbook.add_format({
        'bold': True, 'text_wrap': True, 'valign': 'vcenter',
        'fg_color': '#D9D9D9', 'border': 1, 'font_color': '#5C5C5C', 'align': 'center'
    })
    read_only_cell_format = workbook.add_format({
        'font_color': '#808080', 'italic': True, 'align': 'center', 'valign': 'vcenter'
    })
    integer_format = workbook.add_format({'num_format': '#,##0', 'align': 'center'})
    decimal_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
    text_center_format = workbook.add_format({'align': 'center'})
    text_left_format = workbook.add_format({'align': 'left'})

    # Write headers to the main sheet
    for col_num, value in enumerate(df.columns.values):
        is_read_only_col = '(ห้ามแก้ไข)' in value or '(ระบบ)' in value or '(URL ระบบ)' in value
        current_header_format = read_only_header_format if is_read_only_col else header_format
        worksheet.write(0, col_num, value, current_header_format)

        # Set initial column widths
        max_len = max(df[value].astype(str).apply(len).max(), len(value)) + 2

        if value == 'ชื่ออะไหล่':
            worksheet.set_column(col_num, col_num, max(max_len, 25), text_left_format)
        elif value == 'Part Number':
            worksheet.set_column(col_num, col_num, max(max_len, 15), text_center_format)
        elif value == 'ยี่ห้อ':
            worksheet.set_column(col_num, col_num, max(max_len, 15), text_left_format)
        elif value == 'หมวดหมู่':
            worksheet.set_column(col_num, col_num, max(max_len, 20), text_left_format)
        elif value == 'คำอธิบาย':
            worksheet.set_column(col_num, col_num, max(max_len, 30), text_left_format)
        elif value == 'สต็อก':
            worksheet.set_column(col_num, col_num, max(max_len, 10), integer_format)
        elif value in ['ทุน', 'ราคาขายปลีก', 'ราคาส่ง 1', 'ราคาส่ง 2', 'ทุน Online']:
            worksheet.set_column(col_num, col_num, max(max_len, 12), decimal_format)
        elif is_read_only_col:
            worksheet.set_column(col_num, col_num, max(max_len, 25), read_only_cell_format)
            if value in ['ID (ห้ามแก้ไข)', 'Barcode ID (ระบบ)', 'ID หมวดหมู่ (ระบบ)', 'ไฟล์รูปภาพ (URL ระบบ)']:
                worksheet.set_column(col_num, col_num, None, None, {'hidden': True})
        else:
            worksheet.set_column(col_num, col_num, max_len)

    # Write data rows with blank rows between categories for Spare Parts
    current_row = 1
    last_category = None

    for index, row_data in df.iterrows():
        current_category = row_data['หมวดหมู่']
        if last_category is not None and current_category != last_category:
            current_row += 1 # Add a blank row between categories

        for col_num, col_name in enumerate(df.columns.values):
            cell_value = row_data[col_name]
            cell_format = None

            is_read_only_col = '(ห้ามแก้ไข)' in col_name or '(ระบบ)' in col_name or '(URL ระบบ)' in col_name

            if is_read_only_col:
                cell_format = read_only_cell_format
            elif col_name == 'สต็อก':
                cell_format = integer_format
            elif col_name in ['ทุน', 'ราคาขายปลีก', 'ราคาส่ง 1', 'ราคาส่ง 2', 'ทุน Online']:
                cell_format = decimal_format
            elif col_name in ['ชื่ออะไหล่', 'คำอธิบาย', 'ยี่ห้อ', 'หมวดหมู่']:
                cell_format = text_left_format
            elif col_name == 'Part Number':
                cell_format = text_center_format


            # Handle NaN values by writing None instead of np.nan
            if pd.isna(cell_value):
                worksheet.write(current_row, col_num, None, cell_format) # Write None to produce a blank cell
            else:
                worksheet.write(current_row, col_num, cell_value, cell_format)
        current_row += 1
        last_category = current_category

    # --- Add Freeze Panes ---
    worksheet.freeze_panes(1, 0) # Freeze the first row (headers)

    writer.close()
    output.seek(0)

    return send_file(output, download_name='spare_parts_stock_template.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/import_spare_parts_action', methods=['POST'])
@login_required
def import_spare_parts_action():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการนำเข้าข้อมูลอะไหล่', 'danger')
        return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

    file = request.files['file']

    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

    if file and allowed_excel_file(file.filename):
        try:
            xls = pd.ExcelFile(file)
            if 'Spare Parts Data' not in xls.sheet_names:
                flash('ไม่พบชีทชื่อ "Spare Parts Data" ในไฟล์. โปรดตรวจสอบว่าคุณใช้ไฟล์แม่แบบที่ถูกต้อง', 'danger')
                conn.rollback()
                return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

            df = xls.parse('Spare Parts Data', dtype={'Barcode ID (ระบบ)': str})

            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            # Expected column names now match the export format
            expected_spare_part_cols = [
                'ชื่ออะไหล่', 'Part Number', 'ยี่ห้อ', 'หมวดหมู่', 'คำอธิบาย', 'สต็อก',
                'ทุน', 'ราคาขายปลีก', 'ราคาส่ง 1', 'ราคาส่ง 2', 'ทุน Online'
            ]

            # Check if all required columns are present
            if not all(col in df.columns for col in expected_spare_part_cols):
                missing_cols = [col for col in expected_spare_part_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                conn.rollback()
                return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

            # Cache categories for faster lookup
            cached_categories = {cat['name'].lower(): cat['id'] for cat in database.get_all_spare_part_categories(conn)}
            # Also need reverse lookup for id to name if category_id is provided directly but name is preferred for error messages
            cached_category_names = {cat['id']: cat['name'] for cat in database.get_all_spare_part_categories(conn)}


            for index, row in df.iterrows():
                # Skip blank rows
                if pd.isna(row.get('ชื่ออะไหล่')) and \
                   pd.isna(row.get('สต็อก')) and \
                   pd.isna(row.get('ราคาขายปลีก')):
                    error_rows.append(f"แถวที่ {index + 2}: ข้อมูลหลัก (ชื่ออะไหล่, สต็อก, ราคาขายปลีก) ว่างเปล่า. แถวถูกข้าม.")
                    continue

                try:
                    spare_part_id_from_excel = int(row.get('ID (ห้ามแก้ไข)')) if pd.notna(row.get('ID (ห้ามแก้ไข)')) else None
                    barcode_id_from_excel = str(row.get('Barcode ID (ระบบ)', '')).strip()
                    category_id_from_excel_raw = row.get('ID หมวดหมู่ (ระบบ)') # From system
                    category_name_from_excel = str(row.get('หมวดหมู่', '')).strip().lower() # From user input

                    barcode_id_to_save = None
                    if barcode_id_from_excel and barcode_id_from_excel.lower() not in ['none', 'nan']:
                        barcode_id_to_save = barcode_id_from_excel

                    name = str(row.get('ชื่ออะไหล่', '')).strip()
                    part_number = str(row.get('Part Number', '')).strip()
                    brand = str(row.get('ยี่ห้อ', '')).strip().lower()
                    description = str(row.get('คำอธิบาย', '')).strip()
                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    retail_price_raw = row.get('ราคาขายปลีก')
                    cost_raw = row.get('ทุน')
                    wholesale_price1_raw = row.get('ราคาส่ง 1')
                    wholesale_price2_raw = row.get('ราคาส่ง 2')
                    cost_online_raw = row.get('ทุน Online')

                    if not name or pd.isna(retail_price_raw):
                         raise ValueError("ข้อมูล 'ชื่ออะไหล่' หรือ 'ราคาขายปลีก' ไม่สามารถเว้นว่างได้")

                    # Resolve category_id
                    category_id_to_use = None
                    if pd.notna(category_id_from_excel_raw):
                        try:
                            category_id_to_use = int(category_id_from_excel_raw)
                            # Verify if ID matches name for consistency, or just use ID if provided by system
                            if category_id_to_use not in cached_category_names:
                                raise ValueError(f"ID หมวดหมู่ (ระบบ) '{category_id_to_use}' ไม่ถูกต้องหรือไม่มีในระบบ")
                        except ValueError:
                            raise ValueError(f"ID หมวดหมู่ (ระบบ) '{category_id_from_excel_raw}' ไม่ใช่ตัวเลขที่ถูกต้อง")
                    elif category_name_from_excel:
                        category_id_to_use = cached_categories.get(category_name_from_excel)
                        if category_id_to_use is None:
                            raise ValueError(f"หมวดหมู่ '{category_name_from_excel}' ไม่มีในระบบ. โปรดสร้างหมวดหมู่นี้ก่อน หรือใช้หมวดหมู่ที่มีอยู่แล้ว.")

                    try:
                        retail_price = float(retail_price_raw)
                        cost = float(cost_raw) if pd.notna(cost_raw) else None
                        wholesale_price1 = float(wholesale_price1_raw) if pd.notna(wholesale_price1_raw) else None
                        wholesale_price2 = float(wholesale_price2_raw) if pd.notna(wholesale_price2_raw) else None
                        cost_online = float(cost_online_raw) if pd.notna(cost_online_raw) else None
                    except ValueError as ve:
                        raise ValueError(f"ข้อมูลตัวเลขไม่ถูกต้องในคอลัมน์ราคาหรือทุน: {ve}")

                    cursor = conn.cursor()
                    is_postgres = "psycopg2" in str(type(conn))

                    existing_spare_part = None
                    if spare_part_id_from_excel:
                        existing_spare_part = database.get_spare_part(conn, spare_part_id_from_excel)

                    if not existing_spare_part and barcode_id_to_save:
                        existing_spare_part_id_by_barcode = database.get_spare_part_id_by_barcode(conn, barcode_id_to_save)
                        if existing_spare_part_id_by_barcode:
                            conn.rollback()
                            existing_spare_part = database.get_spare_part(conn, existing_spare_part_id_by_barcode)
                            if existing_spare_part and existing_spare_part['id'] != spare_part_id_from_excel and spare_part_id_from_excel is not None:
                                raise ValueError(f"ID ({spare_part_id_from_excel}) ใน Excel ไม่ตรงกับ ID ที่พบจาก Barcode ({existing_spare_part_id_by_barcode}).")
                        # Check against tires and wheels too
                        if database.get_tire_id_by_barcode(conn, barcode_id_to_save):
                            raise ValueError(f"Barcode ID '{barcode_id_to_save}' ซ้ำกับยาง. Barcode ID ต้องไม่ซ้ำกันข้ามประเภทสินค้า.")
                        if database.get_wheel_id_by_barcode(conn, barcode_id_to_save):
                            raise ValueError(f"Barcode ID '{barcode_id_to_save}' ซ้ำกับล้อแม็ก. Barcode ID ต้องไม่ซ้ำกันข้ามประเภทสินค้า.")


                    # Try to find by name, part_number, and brand as last resort for existing item
                    if not existing_spare_part:
                        if part_number:
                            if is_postgres:
                                cursor.execute("SELECT id, quantity FROM spare_parts WHERE name = %s AND part_number = %s", (name, part_number))
                            else:
                                cursor.execute("SELECT id, quantity FROM spare_parts WHERE name = ? AND part_number = ?", (name, part_number))
                        else: # Fallback to name and brand if no part number
                            if is_postgres:
                                cursor.execute("SELECT id, quantity FROM spare_parts WHERE name = %s AND brand = %s", (name, brand))
                            else:
                                cursor.execute("SELECT id, quantity FROM spare_parts WHERE name = ? AND brand = ?", (name, brand))

                        found_spare_part_data = cursor.fetchone()
                        if found_spare_part_data:
                            existing_spare_part = dict(found_spare_part_data)
                            if existing_spare_part and existing_spare_part['id'] != spare_part_id_from_excel and spare_part_id_from_excel is not None:
                                raise ValueError(f"ID ({spare_part_id_from_excel}) ใน Excel ไม่ตรงกับสินค้าที่มีอยู่แล้วด้วย ชื่อ/Part Number/ยี่ห้อ ({existing_spare_part['id']}).")


                    if existing_spare_part:
                        spare_part_id = existing_spare_part['id']
                        if barcode_id_to_save and not database.get_spare_part_id_by_barcode(conn, barcode_id_to_save):
                            database.add_spare_part_barcode(conn, spare_part_id, barcode_id_to_save, is_primary=False)

                        database.update_spare_part_import(conn, spare_part_id, name, part_number, brand, description,
                                                           quantity, cost, retail_price, wholesale_price1, wholesale_price2,
                                                           cost_online, row.get('ไฟล์รูปภาพ (URL ระบบ)'), category_id_to_use) # Use existing image URL from excel

                        old_quantity = existing_spare_part['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_spare_part_movement(conn, spare_part_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)", None, user_id=current_user.id)
                        updated_count += 1

                    else: # New spare part
                        new_spare_part_id = database.add_spare_part_import(conn, name, part_number, brand, description, quantity,
                                                                            cost, retail_price, wholesale_price1, wholesale_price2,
                                                                            cost_online, row.get('ไฟล์รูปภาพ (URL ระบบ)'), category_id_to_use)
                        if barcode_id_to_save:
                            database.add_spare_part_barcode(conn, new_spare_part_id, barcode_id_to_save, is_primary=True)
                        database.add_spare_part_movement(conn, new_spare_part_id, 'IN', quantity, quantity, "Import from Excel (initial stock)", None, user_id=current_user.id)
                        imported_count += 1

                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")

            conn.commit()
            cache.delete_memoized(get_all_spare_parts_cached)
            cache.delete_memoized(get_cached_spare_part_brands)
            cache.delete_memoized(get_cached_spare_part_categories_hierarchical) # New categories might be referenced
            cache.delete_memoized(get_cached_unread_notification_count) # Notifications from movements

            message = f'นำเข้าข้อมูลอะไหล่สำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:5])}{"..." if len(error_rows) > 5 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')

            return redirect(url_for('stock.export_import', tab='spare_parts_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดร้ายแรงในการนำเข้าไฟล์ Excel ของอะไหล่: {e}', 'danger')
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('stock.export_import', tab='spare_parts_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        conn.rollback()
        return redirect(url_for('stock.export_import', tab='spare_parts_excel'))


# --- User management routes (assuming these are already in your app.py) ---
@bp.route('/manage_users')
@login_required
def manage_users():
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้าจัดการผู้ใช้', 'danger')
        return redirect(url_for('stock.index'))
        
    conn = get_db()
    users = database.get_all_users(conn)
    return render_template('manage_users.html', users=users, current_user=current_user)

@bp.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_new_user():
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์ในการเพิ่มผู้ใช้', 'danger')
        return redirect(url_for('stock.manage_users'))
        
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
                conn.commit()
                return redirect(url_for('stock.manage_users'))
            else:
                flash(f'ชื่อผู้ใช้ "{username}" มีอยู่ในระบบแล้ว', 'danger')
                conn.rollback()
    return render_template('add_user.html', username=request.form.get('username', ''), role=request.form.get('role', 'viewer'), current_user=current_user)

@bp.route('/edit_user_role/<int:user_id>', methods=['POST'])
@login_required
def edit_user_role(user_id):
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์ในการแก้ไขบทบาทผู้ใช้', 'danger')
        return redirect(url_for('stock.manage_users'))
    
    if str(user_id) == current_user.get_id():
        flash('ไม่สามารถแก้ไขบทบาทของผู้ใช้ที่กำลังเข้าสู่ระบบอยู่ได้', 'danger')
        conn.rollback()
        return redirect(url_for('stock.manage_users'))

    new_role = request.form.get('role')
    allowed_roles = ['admin', 'editor', 'retail_sales', 'wholesale_sales', 'viewer', 'accountant']
    if new_role not in allowed_roles:
        flash('บทบาทไม่ถูกต้อง', 'danger')
        conn.rollback()
        return redirect(url_for('stock.manage_users'))

    conn = get_db()
    success = database.update_user_role(conn, user_id, new_role)
    if success:
        flash(f'แก้ไขบทบาทผู้ใช้ ID {user_id} เป็น "{new_role}" สำเร็จ!', 'success')
        conn.commit()
    else:
        flash(f'เกิดข้อผิดพลาดในการแก้ไขบทบาทผู้ใช้ ID {user_id}', 'danger')
        conn.rollback()
    return redirect(url_for('stock.manage_users'))

@bp.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์ในการลบผู้ใช้', 'danger')
        conn.rollback()
        return redirect(url_for('stock.manage_users'))

    conn = get_db()
    if str(user_id) == current_user.get_id():
        flash('ไม่สามารถลบผู้ใช้ที่กำลังเข้าสู่ระบบอยู่ได้', 'danger')
        conn.rollback()
    else:
        database.delete_user(conn, user_id)
        flash('ลบผู้ใช้สำเร็จ!', 'success')
        conn.commit()
    return redirect(url_for('stock.manage_users'))

# --- Admin Dashboard routes (assuming these are already in your app.py) ---
@bp.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึง Admin Dashboard', 'danger')
        return redirect(url_for('stock.index'))

    # --- START: Logic ใหม่สำหรับลบ Log โดยใช้ฐานข้อมูล ---
    CLEANUP_INTERVAL_DAYS = 7
    conn = get_db()

    needs_cleanup = False
    try:
        last_cleanup_str = database.get_setting(conn, 'last_log_cleanup')

        if last_cleanup_str:
            last_cleanup_time = datetime.fromisoformat(last_cleanup_str)
            if (datetime.now() - last_cleanup_time).days >= CLEANUP_INTERVAL_DAYS:
                needs_cleanup = True
        else:
            # ถ้ายังไม่เคยมีการตั้งค่านี้ ให้ทำการล้างครั้งแรก
            needs_cleanup = True

        if needs_cleanup:
            deleted_count = database.delete_old_activity_logs(conn, days=CLEANUP_INTERVAL_DAYS)
            # บันทึกเวลาปัจจุบันลงฐานข้อมูลเป็นการล้างครั้งล่าสุด
            database.set_setting(conn, 'last_log_cleanup', datetime.now().isoformat())
            conn.commit() # Commit ทั้งการลบ Log และการอัปเดตค่า setting

            flash(f'ล้างประวัติการใช้งานที่เก่ากว่า {CLEANUP_INTERVAL_DAYS} วันเรียบร้อยแล้ว (ลบไป {deleted_count} รายการ)', 'info')
            print(f"AUTOMATIC LOG CLEANUP: Deleted {deleted_count} old activity logs.")

    except Exception as e:
        conn.rollback()
        print(f"Error during automatic log cleanup: {e}")
        flash('เกิดข้อผิดพลาดระหว่างการล้างประวัติการใช้งานอัตโนมัติ', 'warning')
    # --- END: Logic ใหม่ ---
    return render_template('admin_dashboard.html', current_user=current_user)

@bp.route('/admin_deleted_items')
@login_required
def admin_deleted_items():
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้ารายการสินค้าที่ถูกลบ', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    deleted_tires = database.get_deleted_tires(conn)
    deleted_wheels = database.get_deleted_wheels(conn)
    deleted_spare_parts = database.get_deleted_spare_parts(conn) # NEW

    active_tab = request.args.get('tab', 'deleted_tires')

    return render_template('admin_deleted_items.html',
                           deleted_tires=deleted_tires,
                           deleted_wheels=deleted_wheels,
                           deleted_spare_parts=deleted_spare_parts, # NEW
                           active_tab=active_tab,
                           current_user=current_user)

@bp.route('/restore_tire/<int:tire_id>', methods=['POST'])
@login_required
def restore_tire_action(tire_id):
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์ในการกู้คืนยาง', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    try:
        database.restore_tire(conn, tire_id)
        flash(f'กู้คืนยาง ID {tire_id} สำเร็จ!', 'success')
        conn.commit()
        cache.delete_memoized(get_all_tires_list_cached)
        cache.delete_memoized(get_cached_tire_brands)
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการกู้คืนยาง: {e}', 'danger')
        conn.rollback()
    return redirect(url_for('stock.admin_deleted_items', tab='deleted_tires'))

@bp.route('/restore_wheel/<int:wheel_id>', methods=['POST'])
@login_required
def restore_wheel_action(wheel_id):
    # Check permission directly inside the route function
    if not current_user.is_admin(): # Only Admin
        flash('คุณไม่มีสิทธิ์ในการกู้คืนแม็ก', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    try:
        database.restore_wheel(conn, wheel_id)
        flash(f'กู้คืนแม็ก ID {wheel_id} สำเร็จ!', 'success')
        conn.commit()
        cache.delete_memoized(get_all_wheels_list_cached)
        cache.delete_memoized(get_cached_wheel_brands)
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการกู้คืนแม็ก: {e}', 'danger')
        conn.rollback()
    return redirect(url_for('stock.admin_deleted_items', tab='deleted_wheels'))

@bp.route('/restore_spare_part/<int:spare_part_id>', methods=['POST'])
@login_required
def restore_spare_part_action(spare_part_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการกู้คืนอะไหล่', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    try:
        database.restore_spare_part(conn, spare_part_id)
        flash(f'กู้คืนอะไหล่ ID {spare_part_id} สำเร็จ!', 'success')
        conn.commit()
        cache.delete_memoized(get_all_spare_parts_cached)
        cache.delete_memoized(get_cached_spare_part_brands)
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการกู้คืนอะไหล่: {e}', 'danger')
        conn.rollback()
    return redirect(url_for('stock.admin_deleted_items', tab='deleted_spare_parts'))

@bp.route('/barcode_scanner_page') # Renamed to avoid conflict with barcode_scanner route
@login_required
def barcode_scanner_page():
    """Renders the barcode scanning page."""
    # Check permission directly inside the route function
    # Retail sales can use barcode scanner for IN/OUT, but OUT is restricted by API
    if not (current_user.is_admin() or current_user.is_editor() or current_user.is_retail_sales() or current_user.is_wholesale_sales()):
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้าสแกนบาร์โค้ด', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    sales_channels = get_all_sales_channels_cached()
    online_platforms = get_all_online_platforms_cached()
    wholesale_customers = get_all_wholesale_customers_cached()

    # --- START: โค้ดดึงข้อมูลประวัติล่าสุด (เวอร์ชันอัปเดต) ---
    cursor = conn.cursor()

    # Query for last 10 tire movements (with all required columns)
    tire_movements_query = """
        SELECT tm.id, tm.timestamp, tm.type, tm.quantity_change, tm.remaining_quantity, tm.image_filename, tm.notes,
               t.id AS tire_main_id, t.brand, t.model, t.size,
               u.username AS user_username,
               sc.name AS channel_name,
               op.name AS online_platform_name,
               wc.name AS wholesale_customer_name,
               tm.return_customer_type, tm.channel_id, tm.online_platform_id, tm.wholesale_customer_id
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        LEFT JOIN users u ON tm.user_id = u.id
        LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
        LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
        ORDER BY tm.timestamp DESC LIMIT 20
    """
    cursor.execute(tire_movements_query)
    recent_tire_movements_raw = cursor.fetchall()

    # Query for last 10 wheel movements (with all required columns)
    wheel_movements_query = """
        SELECT wm.id, wm.timestamp, wm.type, wm.quantity_change, wm.remaining_quantity, wm.image_filename, wm.notes,
               w.id AS wheel_main_id, w.brand, w.model, w.diameter, w.pcd, w.width, w.et,
               u.username AS user_username,
               sc.name AS channel_name,
               op.name AS online_platform_name,
               wc.name AS wholesale_customer_name,
               wm.return_customer_type, wm.channel_id, wm.online_platform_id, wm.wholesale_customer_id
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        LEFT JOIN users u ON wm.user_id = u.id
        LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
        LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
        ORDER BY wm.timestamp DESC LIMIT 20
    """
    cursor.execute(wheel_movements_query)
    recent_wheel_movements_raw = cursor.fetchall()
    
    # Query for last 10 spare part movements (with all required columns)
    spare_part_movements_query = """
        SELECT spm.id, spm.timestamp, spm.type, spm.quantity_change, spm.remaining_quantity, spm.image_filename, spm.notes,
               sp.id AS spare_part_main_id, sp.name AS spare_part_name, sp.part_number, sp.brand AS spare_part_brand,
               u.username AS user_username,
               sc.name AS channel_name,
               op.name AS online_platform_name,
               wc.name AS wholesale_customer_name,
               spm.return_customer_type, spm.channel_id, spm.online_platform_id, spm.wholesale_customer_id
        FROM spare_part_movements spm
        JOIN spare_parts sp ON spm.spare_part_id = sp.id
        LEFT JOIN users u ON spm.user_id = u.id
        LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
        LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
        ORDER BY spm.timestamp DESC LIMIT 20
    """
    cursor.execute(spare_part_movements_query)
    recent_spare_part_movements_raw = cursor.fetchall()
    cursor.close()

    # Process timestamps to BKK time
    recent_tire_movements = [dict(m, timestamp=database.convert_to_bkk_time(m['timestamp'])) for m in recent_tire_movements_raw]
    recent_wheel_movements = [dict(m, timestamp=database.convert_to_bkk_time(m['timestamp'])) for m in recent_wheel_movements_raw]
    recent_spare_part_movements = [dict(m, timestamp=database.convert_to_bkk_time(m['timestamp'])) for m in recent_spare_part_movements_raw]
    # --- END: โค้ดดึงข้อมูลประวัติล่าสุด ---

    return render_template('barcode_scanner.html',
                           current_user=current_user,
                           sales_channels=sales_channels,
                           online_platforms=online_platforms,
                           wholesale_customers=wholesale_customers,
                           # --- START: ส่งตัวแปรใหม่ไปที่ Template ---
                           recent_tire_movements=recent_tire_movements,
                           recent_wheel_movements=recent_wheel_movements,
                           recent_spare_part_movements=recent_spare_part_movements
                           # --- END: ส่งตัวแปรใหม่ไปที่ Template ---
                           )

@bp.route('/api/scan_item_lookup', methods=['GET'])
@login_required
def api_scan_item_lookup():
    scanned_barcode_string = request.args.get('barcode_id')
    if not scanned_barcode_string:
        conn.rollback()
        return jsonify({"success": False, "message": "ไม่พบบาร์โค้ด"}), 400

    conn = get_db()

    # Try to find in Tires
    tire_id = database.get_tire_id_by_barcode(conn, scanned_barcode_string)
    if tire_id:
        tire = database.get_tire(conn, tire_id)
        if tire and not tire['is_deleted']: # Only return active items
            if not isinstance(tire, dict):
                tire = dict(tire)
            tire['type'] = 'tire'
            tire['current_quantity'] = tire['quantity']
            return jsonify({"success": True, "item": tire})

    # Try to find in Wheels
    wheel_id = database.get_wheel_id_by_barcode(conn, scanned_barcode_string)
    if wheel_id:
        wheel = database.get_wheel(conn, wheel_id)
        if wheel and not wheel['is_deleted']: # Only return active items
            if not isinstance(wheel, dict):
                wheel = dict(wheel)
            wheel['type'] = 'wheel'
            wheel['current_quantity'] = wheel['quantity']
            return jsonify({"success": True, "item": wheel})

    # NEW: Try to find in Spare Parts
    spare_part_id = database.get_spare_part_id_by_barcode(conn, scanned_barcode_string)
    if spare_part_id:
        spare_part = database.get_spare_part(conn, spare_part_id)
        if spare_part and not spare_part['is_deleted']: # Only return active items
            if not isinstance(spare_part, dict):
                spare_part = dict(spare_part)
            spare_part['type'] = 'spare_part'
            spare_part['current_quantity'] = spare_part['quantity']
            return jsonify({"success": True, "item": spare_part})


    return jsonify({
        "success": False,
        "message": f"ไม่พบสินค้าสำหรับบาร์โค้ด: '{scanned_barcode_string}'. คุณต้องการเชื่อมโยงบาร์โค้ดนี้กับสินค้าที่มีอยู่หรือไม่?",
        "action_required": "link_new_barcode",
        "scanned_barcode": scanned_barcode_string
    }), 404

@bp.route('/api/process_stock_transaction', methods=['POST'])
@login_required
def api_process_stock_transaction():
    conn = get_db()
    
    try:
        # รับข้อมูลจาก FormData
        transaction_type = request.form.get('type')
        items_json = request.form.get('items_json')
        notes = request.form.get('notes', '').strip()
        user_id = current_user.id
        
        # แปลง JSON string ของรายการสินค้ากลับเป็น Python list
        items_to_process = json.loads(items_json) if items_json else []

        # ตรวจสอบข้อมูลพื้นฐาน
        if transaction_type not in ['IN', 'OUT', 'RETURN']:
            return jsonify({"success": False, "message": "ประเภทการทำรายการไม่ถูกต้อง"}), 400
        if not items_to_process:
            return jsonify({"success": False, "message": "ไม่มีรายการสินค้าให้ทำรายการ"}), 400

        # ตรวจสอบสิทธิ์: 'OUT' ต้องเป็น Admin หรือ Editor
        if transaction_type == 'OUT' and not current_user.can_edit():
            return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการจ่ายสินค้าออกจากสต็อก"}), 403

        # อัปโหลดรูปภาพ (ถ้ามี)
        bill_image_url_to_db = None
        if 'bill_image' in request.files:
            bill_image_file = request.files['bill_image']
            if bill_image_file and bill_image_file.filename != '':
                if allowed_image_file(bill_image_file.filename):
                    upload_result = cloudinary.uploader.upload(bill_image_file)
                    bill_image_url_to_db = upload_result['secure_url']
                else:
                    return jsonify({"success": False, "message": "ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง"}), 400
        
        # --- Channel Validation Logic ---
        channel_id_str = request.form.get('channel_id')
        online_platform_id_str = request.form.get('online_platform_id')
        wholesale_customer_id_str = request.form.get('wholesale_customer_id')
        return_customer_type = request.form.get('return_customer_type')
        return_wholesale_customer_id_str = request.form.get('return_wholesale_customer_id')
        return_online_platform_id_str = request.form.get('return_online_platform_id')

        final_channel_id = int(channel_id_str) if channel_id_str else None
        final_online_platform_id = None
        final_wholesale_customer_id = None

        channel_name = database.get_sales_channel_name(conn, final_channel_id)

        if transaction_type == 'IN':
            if channel_name != 'ซื้อเข้า':
                return jsonify({"success": False, "message": 'สำหรับประเภท "รับเข้า" ช่องทางต้องเป็น "ซื้อเข้า" เท่านั้น'}), 400
            return_customer_type = None

        elif transaction_type == 'RETURN':
            if channel_name != 'รับคืน':
                return jsonify({"success": False, "message": 'สำหรับประเภท "รับคืน/ตีคืน" ช่องทางต้องเป็น "รับคืน" เท่านั้น'}), 400
            if not return_customer_type:
                return jsonify({"success": False, "message": 'กรุณาระบุ "คืนจาก" สำหรับประเภท "รับคืน/ตีคืน"'}), 400

            if return_customer_type == 'ออนไลน์':
                if not return_online_platform_id_str:
                    return jsonify({"success": False, "message": 'กรุณาระบุ "แพลตฟอร์มออนไลน์ที่คืน"'}), 400
                final_online_platform_id = int(return_online_platform_id_str)
            elif return_customer_type == 'หน้าร้านร้านยาง':
                if not return_wholesale_customer_id_str:
                    return jsonify({"success": False, "message": 'กรุณาระบุ "ชื่อร้านยางที่คืน"'}), 400
                final_wholesale_customer_id = int(return_wholesale_customer_id_str)

        elif transaction_type == 'OUT':
            if channel_name in ['ซื้อเข้า', 'รับคืน']:
                return jsonify({"success": False, "message": f'สำหรับ "จ่ายออก" ช่องทางไม่สามารถเป็น "{channel_name}" ได้'}), 400
            if channel_name == 'ออนไลน์':
                if not online_platform_id_str:
                    return jsonify({"success": False, "message": 'กรุณาระบุ "แพลตฟอร์มออนไลน์"'}), 400
                final_online_platform_id = int(online_platform_id_str)
            elif channel_name == 'ค้าส่ง':
                if not wholesale_customer_id_str:
                    return jsonify({"success": False, "message": 'กรุณาระบุ "ชื่อลูกค้าค้าส่ง"'}), 400
                final_wholesale_customer_id = int(wholesale_customer_id_str)
            return_customer_type = None
        
        # --- Process each item in the list ---
        tires_moved, wheels_moved, spare_parts_moved = False, False, False

        for item_data in items_to_process:
            item_id = item_data.get('id')
            item_type = item_data.get('item_type')
            quantity_change = item_data.get('quantity')

            if not all([item_id, item_type, quantity_change, isinstance(quantity_change, int), quantity_change > 0]):
                raise ValueError(f"ข้อมูลสินค้าไม่สมบูรณ์สำหรับรายการ ID: {item_id}")

            if item_type == 'tire':
                db_item = database.get_tire(conn, item_id)
                update_quantity_func = database.update_tire_quantity
                add_movement_func = database.add_tire_movement
                tires_moved = True
            elif item_type == 'wheel':
                db_item = database.get_wheel(conn, item_id)
                update_quantity_func = database.update_wheel_quantity
                add_movement_func = database.add_wheel_movement
                wheels_moved = True
            elif item_type == 'spare_part':
                db_item = database.get_spare_part(conn, item_id)
                update_quantity_func = database.update_spare_part_quantity
                add_movement_func = database.add_spare_part_movement
                spare_parts_moved = True
            else:
                raise ValueError(f"ประเภทสินค้าไม่ถูกต้อง: {item_type}")

            if not db_item:
                raise ValueError(f"ไม่พบสินค้า ID {item_id} ประเภท {item_type} ในฐานข้อมูล")
            
            current_qty = db_item['quantity']
            new_qty = current_qty
            if transaction_type in ['IN', 'RETURN']:
                new_qty += quantity_change
            elif transaction_type == 'OUT':
                if current_qty < quantity_change:
                    item_name = db_item.get('name') or f"{db_item.get('brand')} {db_item.get('model')}"
                    raise ValueError(f"สต็อกไม่พอสำหรับ {item_name} (มีอยู่: {current_qty}, ต้องการ: {quantity_change})")
                new_qty -= quantity_change

            update_quantity_func(conn, item_id, new_qty)
            add_movement_func(conn, item_id, transaction_type, quantity_change, new_qty, notes, 
                              bill_image_url_to_db, user_id, final_channel_id,
                              final_online_platform_id, final_wholesale_customer_id, return_customer_type)

        conn.commit()
        if tires_moved: cache.delete_memoized(get_all_tires_list_cached)
        if wheels_moved: cache.delete_memoized(get_all_wheels_list_cached)
        if spare_parts_moved: 
            cache.delete_memoized(get_all_spare_parts_cached)
        
        return jsonify({"success": True, "message": f"ทำรายการ {transaction_type} สำเร็จสำหรับ {len(items_to_process)} ประเภทสินค้า"}), 200

    except ValueError as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Stock transaction failed: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการทำรายการ: {str(e)}"}), 500

@bp.route('/api/search_items_for_link', methods=['GET'])
@login_required
def api_search_items_for_link():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return jsonify({"success": False, "message": "กรุณาใส่คำค้นหา"}), 400

    conn = get_db()

    cursor = conn.cursor() # Use cursor for all DB types for consistency with psycopg2.DictCursor

    items = []

    # Search in Tires
    tire_search_query = f"""
        SELECT id, brand, model, size, quantity AS current_quantity
        FROM tires
        WHERE is_deleted = FALSE AND (
            LOWER(brand) LIKE %s OR
            LOWER(model) LIKE %s OR
            LOWER(size) LIKE %s
        )
        ORDER BY brand, model, size
        LIMIT 20
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(tire_search_query, (f"%{query}%", f"%{query}%", f"%{query}%"))
    else:
        tire_search_query_sqlite = tire_search_query.replace('%s', '?').replace('ILIKE', 'LIKE')
        cursor.execute(tire_search_query_sqlite, (f"%{query}%", f"%{query}%", f"%{query}%"))

    for row in cursor.fetchall():
        item = dict(row)
        item['type'] = 'tire'
        items.append(item)

    # Search in Wheels
    wheel_size_search_col = "(w.diameter || 'x' || w.width || ' ' || w.pcd)"
    if "psycopg2" in str(type(conn)):
        wheel_size_search_col = "CONCAT(w.diameter, 'x', w.width, ' ', w.pcd)" # For PostgreSQL

    wheel_search_query = f"""
        SELECT id, brand, model, diameter, pcd, width, quantity AS current_quantity
        FROM wheels w
        WHERE is_deleted = FALSE AND (
            LOWER(brand) LIKE %s OR
            LOWER(model) LIKE %s OR
            LOWER(pcd) LIKE %s OR
            {wheel_size_search_col} LIKE %s
        )
        ORDER BY brand, model, diameter
        LIMIT 20
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(wheel_search_query, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"))
    else:
        wheel_search_query_sqlite = wheel_search_query.replace('%s', '?').replace('ILIKE', 'LIKE')
        cursor.execute(wheel_search_query_sqlite, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"))

    for row in cursor.fetchall():
        item = dict(row)
        item['type'] = 'wheel'
        items.append(item)

    # NEW: Search in Spare Parts
    spare_part_search_query = f"""
        SELECT sp.id, sp.name, sp.part_number, sp.brand, sp.quantity AS current_quantity
        FROM spare_parts sp
        WHERE is_deleted = FALSE AND (
            LOWER(sp.name) LIKE %s OR
            LOWER(sp.part_number) LIKE %s OR
            LOWER(sp.brand) LIKE %s
        )
        ORDER BY sp.name, sp.brand
        LIMIT 20
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(spare_part_search_query, (f"%{query}%", f"%{query}%", f"%{query}%"))
    else:
        spare_part_search_query_sqlite = spare_part_search_query.replace('%s', '?').replace('ILIKE', 'LIKE')
        cursor.execute(spare_part_search_query_sqlite, (f"%{query}%", f"%{query}%", f"%{query}%"))

    for row in cursor.fetchall():
        item = dict(row)
        item['type'] = 'spare_part'
        items.append(item)

    cursor.close()

    return jsonify({"success": True, "items": items}), 200

@bp.route('/api/link_barcode_to_item', methods=['POST'])
@login_required
def api_link_barcode_to_item():
    data = request.get_json()
    scanned_barcode = data.get('scanned_barcode')
    item_id = data.get('item_id')
    item_type = data.get('item_type')

    if not scanned_barcode or not item_id or not item_type:
        return jsonify({"success": False, "message": "ข้อมูลไม่สมบูรณ์สำหรับการเชื่อมโยงบาร์โค้ด"}), 400

    conn = get_db()
    try:
        # Check if barcode exists for any item type
        existing_tire_barcode_id = database.get_tire_id_by_barcode(conn, scanned_barcode)
        existing_wheel_barcode_id = database.get_wheel_id_by_barcode(conn, scanned_barcode)
        existing_spare_part_barcode_id = database.get_spare_part_id_by_barcode(conn, scanned_barcode) # NEW

        if existing_tire_barcode_id or existing_wheel_barcode_id or existing_spare_part_barcode_id: # NEW
            # If it exists and is already linked to *this* item, just return success
            if (item_type == 'tire' and existing_tire_barcode_id == item_id) or \
               (item_type == 'wheel' and existing_wheel_barcode_id == item_id) or \
               (item_type == 'spare_part' and existing_spare_part_barcode_id == item_id): # NEW
                return jsonify({"success": True, "message": f"บาร์โค้ด '{scanned_barcode}' ถูกเชื่อมโยงกับสินค้านี้อยู่แล้ว"}), 200
            else:
                # If it exists and is linked to a *different* item (or different type)
                return jsonify({"success": False, "message": f"บาร์โค้ด '{scanned_barcode}' มีอยู่ในระบบแล้ว และถูกเชื่อมโยงกับสินค้าอื่น"}), 409

        if item_type == 'tire':
            database.add_tire_barcode(conn, item_id, scanned_barcode, is_primary=False)
        elif item_type == 'wheel':
            database.add_wheel_barcode(conn, item_id, scanned_barcode, is_primary=False)
        elif item_type == 'spare_part': # NEW
            database.add_spare_part_barcode(conn, item_id, scanned_barcode, is_primary=False)
        else:
            conn.rollback()
            return jsonify({"success": False, "message": "ประเภทสินค้าไม่ถูกต้อง (ต้องเป็น tire, wheel, หรือ spare_part)"}), 400

        conn.commit()
        return jsonify({"success": True, "message": f"เชื่อมโยงบาร์โค้ด '{scanned_barcode}' กับสินค้าสำเร็จ!"}), 200

    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error linking barcode: {e}", exc_info=True) # Log the full error
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการเชื่อมโยงบาร์โค้ด: {str(e)}"}), 500
        

@bp.route('/manage_wholesale_customers')
@login_required
def manage_wholesale_customers():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้าจัดการลูกค้าค้าส่ง', 'danger')
        return redirect(url_for('stock.index'))
    
    conn = get_db()
    wholesale_customers = database.get_all_wholesale_customers(conn)
    return render_template('manage_wholesale_customers.html', 
                           wholesale_customers=wholesale_customers,
                           current_user=current_user)

@bp.route('/add_wholesale_customer_action', methods=['POST'])
@login_required
def add_wholesale_customer_action():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการเพิ่มลูกค้าค้าส่ง', 'danger')
        return redirect(url_for('stock.manage_wholesale_customers'))
    
    customer_name = request.form.get('customer_name', '').strip()
    if not customer_name:
        flash('กรุณากรอกชื่อลูกค้าค้าส่ง', 'danger')
        conn.rollback()
    else:
        conn = get_db()
        customer_id = database.add_wholesale_customer(conn, customer_name)
        if customer_id:
            flash(f'เพิ่มลูกค้าค้าส่ง "{customer_name}" สำเร็จ!', 'success')
            conn.commit()
            cache.delete_memoized(get_all_wholesale_customers_cached)
            cache.delete_memoized(get_cached_wholesale_summary)
        else:
            flash(f'ไม่สามารถเพิ่มลูกค้าค้าส่ง "{customer_name}" ได้ อาจมีชื่อนี้อยู่ในระบบแล้ว', 'warning')
    return redirect(url_for('stock.manage_wholesale_customers'))

@bp.route('/edit_wholesale_customer/<int:customer_id>', methods=['GET', 'POST'])
@login_required
def edit_wholesale_customer(customer_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขลูกค้าค้าส่ง', 'danger')
        return redirect(url_for('stock.manage_wholesale_customers'))
    
    conn = get_db()
    
    # Get customer data as a dictionary
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id, name FROM wholesale_customers WHERE id = %s", (customer_id,))
    else:
        cursor.execute("SELECT id, name FROM wholesale_customers WHERE id = ?", (customer_id,))
    customer_data = cursor.fetchone()
    if customer_data:
        customer_data = dict(customer_data) # Ensure it's a dict
    else:
        flash('ไม่พบลูกค้าค้าส่งที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.manage_wholesale_customers'))


    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        if not new_name:
            flash('กรุณากรอกชื่อลูกค้าค้าส่ง', 'danger')
        else:
            try:
                # Assuming you need a function to update customer name in database.py
                # You might need to add a function like database.update_wholesale_customer_name
                # For now, directly executing SQL
                if "psycopg2" in str(type(conn)):
                    cursor.execute("UPDATE wholesale_customers SET name = %s WHERE id = %s", (new_name, customer_id))
                else:
                    cursor.execute("UPDATE wholesale_customers SET name = ? WHERE id = ?", (new_name, customer_id))
                conn.commit()
                flash(f'แก้ไขชื่อลูกค้าค้าส่งเป็น "{new_name}" สำเร็จ!', 'success')
                cache.delete_memoized(get_all_wholesale_customers_cached)
                cache.delete_memoized(get_cached_wholesale_summary)
                return redirect(url_for('stock.manage_wholesale_customers'))
            except Exception as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
                    flash(f'ชื่อลูกค้าค้าส่ง "{new_name}" มีอยู่ในระบบแล้ว', 'warning')
                else:
                    flash(f'เกิดข้อผิดพลาดในการแก้ไขลูกค้าค้าส่ง: {e}', 'danger')
    
    return render_template('add_edit_wholesale_customer.html', 
                           customer=customer_data,
                           current_user=current_user)

@bp.route('/delete_wholesale_customer/<int:customer_id>', methods=['POST'])
@login_required
def delete_wholesale_customer(customer_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการลบลูกค้าค้าส่ง', 'danger')
        return redirect(url_for('stock.manage_wholesale_customers'))
    
    conn = get_db()
    try:
        # Before deleting a customer, it's good practice to unlink any movements.
        # Setting wholesale_customer_id to NULL in related movements
        cursor = conn.cursor()
        is_postgres = "psycopg2" in str(type(conn))

        if is_postgres:
            cursor.execute("UPDATE tire_movements SET wholesale_customer_id = NULL WHERE wholesale_customer_id = %s", (customer_id,))
            cursor.execute("UPDATE wheel_movements SET wholesale_customer_id = NULL WHERE wholesale_customer_id = %s", (customer_id,))
            cursor.execute("DELETE FROM wholesale_customers WHERE id = %s", (customer_id,))
        else:
            cursor.execute("UPDATE tire_movements SET wholesale_customer_id = NULL WHERE wholesale_customer_id = ?", (customer_id,))
            cursor.execute("UPDATE wheel_movements SET wholesale_customer_id = NULL WHERE wholesale_customer_id = ?", (customer_id,))
            cursor.execute("DELETE FROM wholesale_customers WHERE id = ?", (customer_id,))
        
        conn.commit()
        flash('ลบลูกค้าค้าส่งสำเร็จ!', 'success')
        cache.delete_memoized(get_all_wholesale_customers_cached)
        cache.delete_memoized(get_cached_wholesale_summary)
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดในการลบลูกค้าค้าส่ง: {e}', 'danger')
    
    return redirect(url_for('stock.manage_wholesale_customers'))     

    # ในไฟล์ app.py ลบ @bp.route('/fix-history') เก่าออก แล้วใช้โค้ดนี้แทน

@bp.route('/admin/fix_history', methods=['GET', 'POST'])
@login_required
def fix_history():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))
    
    if request.method == 'POST':
        conn = get_db()
        try:
            # --- START: ส่วนที่แก้ไข ---
            # ตรวจสอบว่าผู้ใช้กดปุ่มไหน
            if 'recalculate_stock' in request.form:
                result = database.recalculate_all_stock_histories(conn)
                flash(f'ซ่อมแซมข้อมูลประวัติสต็อกทั้งหมดสำเร็จ! ({result})', 'success')
            
            elif 'fix_commissions' in request.form:
                fixed_count = database.fix_historical_commission_data(conn)
                flash(f'ซ่อมแซมข้อมูลค่าคอมมิชชั่นในอดีตสำเร็จ! (แก้ไขทั้งหมด {fixed_count} รายการ)', 'success')
            
            conn.commit()
            # --- END: ส่วนที่แก้ไข ---
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดระหว่างซ่อมข้อมูล: {e}', 'danger')
            conn.rollback()
        
        return redirect(url_for('stock.fix_history'))

    return render_template('fix_history.html', current_user=current_user)

@bp.route('/notifications')
@login_required
def notifications():
    conn = get_db()
    all_notifications = database.get_all_notifications(conn)
    return render_template('notifications.html', notifications=all_notifications, current_user=current_user)

@bp.route('/notifications/mark-as-read')
@login_required
def mark_notifications_read():
    conn = get_db()
    try:
        database.mark_all_notifications_as_read(conn)
        conn.commit()
        cache.delete_memoized(get_cached_unread_notification_count)
    except Exception as e:
        conn.rollback()
    return redirect(url_for('stock.notifications'))

@bp.route('/bulk_stock_movement', methods=['POST'])
@login_required
def bulk_stock_movement():
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการทำรายการสต็อก"}), 403

    conn = get_db()

    try:
        # ดึงข้อมูลจากฟอร์ม
        item_type = request.form.get('item_type')
        move_type = request.form.get('type')
        items_json = request.form.get('items_json')
        notes = request.form.get('notes', '').strip()
        user_id = current_user.id

        # ดึงข้อมูลช่องทาง
        channel_id = request.form.get('channel_id')
        online_platform_id = request.form.get('online_platform_id')
        wholesale_customer_id = request.form.get('wholesale_customer_id')
        return_customer_type = request.form.get('return_customer_type')
        return_wholesale_customer_id = request.form.get('return_wholesale_customer_id')
        return_online_platform_id = request.form.get('return_online_platform_id')

        # แปลงค่า ID ให้เป็น integer หรือ None
        final_channel_id = int(channel_id) if channel_id else None
        final_online_platform_id = None
        final_wholesale_customer_id = None

        # Logic สำหรับการคืนสินค้า หรือ การจ่ายออก
        if move_type == 'RETURN':
            if return_customer_type == 'ออนไลน์':
                final_online_platform_id = int(return_online_platform_id) if return_online_platform_id else None
            elif return_customer_type == 'หน้าร้านร้านยาง':
                final_wholesale_customer_id = int(return_wholesale_customer_id) if return_wholesale_customer_id else None
        elif move_type == 'OUT':
             final_online_platform_id = int(online_platform_id) if online_platform_id else None
             final_wholesale_customer_id = int(wholesale_customer_id) if wholesale_customer_id else None

        # อัปโหลดรูปภาพ (ถ้ามี)
        bill_image_url_to_db = None
        if 'bill_image' in request.files:
            bill_image_file = request.files['bill_image']
            if bill_image_file and bill_image_file.filename != '':
                if allowed_image_file(bill_image_file.filename):
                    # --- START: MODIFIED UPLOAD LOGIC ---
                    try:
                        if current_app.config['CLOUDINARY_AVAILABLE']:
                            upload_result = cloudinary.uploader.upload(bill_image_file)
                            bill_image_url_to_db = upload_result['secure_url']
                        else:
                            original_filename = secure_filename(bill_image_file.filename)
                            file_extension = os.path.splitext(original_filename)[1]
                            unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                            
                            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                            bill_image_file.save(filepath)
                            bill_image_url_to_db = url_for('stock.uploaded_file', filename=unique_filename, _external=True)
                    except Exception as e:
                        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาดในการอัปโหลดรูปภาพบิล: {e}"}), 400
                    # --- END: MODIFIED UPLOAD LOGIC ---
                else:
                    return jsonify({"success": False, "message": "ชนิดไฟล์รูปภาพบิลไม่ถูกต้อง"}), 400

        tires_moved, wheels_moved, spare_parts_moved = False, False, False
        items = json.loads(items_json)

        # --- เริ่ม Transaction ---
        for item_data in items:
            item_id = item_data['id']
            quantity_change = item_data['quantity']

            item_name_for_notif = ""
            unit_for_notif = ""

            if item_type == 'tire':
                tires_moved = True
                current_item = database.get_tire(conn, item_id)
                update_quantity_func = database.update_tire_quantity
                add_movement_func = database.add_tire_movement
                item_name_for_notif = f"ยาง: {current_item['brand'].title()} {current_item['model'].title()} ({current_item['size']})"
                unit_for_notif = "เส้น"
            elif item_type == 'wheel':
                wheels_moved = True
                current_item = database.get_wheel(conn, item_id)
                update_quantity_func = database.update_wheel_quantity
                add_movement_func = database.add_wheel_movement
                item_name_for_notif = f"แม็ก: {current_item['brand'].title()} {current_item['model'].title()}"
                unit_for_notif = "วง"
            elif item_type == 'spare_part': # NEW
                spare_parts_moved = True
                current_item = database.get_spare_part(conn, item_id)
                update_quantity_func = database.update_spare_part_quantity
                add_movement_func = database.add_spare_part_movement
                item_name_for_notif = f"อะไหล่: {current_item['name']} ({current_item.get('brand', 'ไม่ระบุยี่ห้อ')})"
                unit_for_notif = "ชิ้น"

            if not current_item:
                raise ValueError(f"ไม่พบสินค้า ID {item_id} ในระบบ")

            current_quantity = current_item['quantity']
            new_quantity = current_quantity
            if move_type in ['IN', 'RETURN']:
                new_quantity += quantity_change
            elif move_type == 'OUT':
                if current_quantity < quantity_change:
                    item_name = f"{current_item['brand']} {current_item['model']}"
                    raise ValueError(f"สต็อกไม่พอสำหรับ {item_name} (มี: {current_quantity}, ต้องการ: {quantity_change})")
                new_quantity -= quantity_change

            update_quantity_func(conn, item_id, new_quantity)
            add_movement_func(conn, item_id, move_type, quantity_change, new_quantity, notes, 
                              bill_image_url_to_db, user_id, final_channel_id,
                              final_online_platform_id, final_wholesale_customer_id, return_customer_type)

            message = (
                f"สต็อก [{move_type}] {item_name_for_notif} "
                f"จำนวน {quantity_change} {unit_for_notif} (คงเหลือ: {new_quantity}) "
                f"โดย {current_user.username}"
            )
            database.add_notification(conn, message, user_id)

        if tires_moved:
            cache.delete_memoized(get_all_tires_list_cached)
            print("--- CACHE CLEARED for Tires ---")

        if wheels_moved:
            cache.delete_memoized(get_all_wheels_list_cached)
            print("--- CACHE CLEARED for Wheels ---")

        if spare_parts_moved:
            cache.delete_memoized(get_all_spare_parts_cached)
            print("--- CACHE CLEARED for Spare Parts ---")

        conn.commit()
        if tires_moved or wheels_moved or spare_parts_moved:
            cache.delete_memoized(get_cached_unread_notification_count)
            print("--- CACHE CLEARED for Unread Notification Count ---")

        return jsonify({"success": True, "message": f"บันทึกการทำรายการ {len(items)} รายการสำเร็จ!"})

    except ValueError as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Bulk stock movement failed: {e}", exc_info=True)
        return jsonify({"success": False, "message": "เกิดข้อผิดพลาดร้ายแรงในเซิร์ฟเวอร์"}), 500

@bp.route('/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    feedback_type = request.form.get('feedback_type')
    message = request.form.get('message')

    if not feedback_type or not message:
        flash('กรุณากรอกข้อมูลให้ครบถ้วน', 'danger')
        return redirect(request.referrer or url_for('index'))

    conn = get_db()
    try:
        user_id = current_user.id
        database.add_feedback(conn, user_id, feedback_type, message)
        conn.commit()
        flash('ขอบคุณสำหรับข้อเสนอแนะ!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดในการส่งข้อเสนอแนะ: {e}', 'danger')

    return redirect(request.referrer or url_for('index'))

@bp.route('/view_feedback')
@login_required
def view_feedback():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    all_feedback = database.get_all_feedback(conn)

    status_order = ['ใหม่', 'กำลังตรวจสอบ', 'แก้ไขแล้ว', 'ไม่ดำเนินการ']

    return render_template('view_feedback.html', 
                           all_feedback=all_feedback, 
                           status_order=status_order,
                           current_user=current_user)

@bp.route('/update_feedback_status/<int:feedback_id>', methods=['POST'])
@login_required
def update_feedback_status(feedback_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ดำเนินการนี้', 'danger')
        conn.rollback()
        return redirect(url_for('stock.view_feedback'))

    new_status = request.form.get('status')
    if not new_status:
        flash('กรุณาเลือกสถานะใหม่', 'danger')
        conn.rollback()
        return redirect(url_for('stock.view_feedback'))

    conn = get_db()
    try:
        database.update_feedback_status(conn, feedback_id, new_status)
        conn.commit()
        flash(f'อัปเดตสถานะของ Feedback ID #{feedback_id} เป็น "{new_status}" สำเร็จ!', 'success')
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการอัปเดตสถานะ: {e}', 'danger')
        conn.rollback()

    return redirect(url_for('stock.view_feedback'))

@bp.route('/manage_announcements', methods=['GET', 'POST'])
@login_required
def manage_announcements():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        is_active = request.form.get('is_active') == 'true'

        if is_active:
            database.deactivate_all_announcements(conn)

        database.add_announcement(conn, title, content, is_active)
        conn.commit()
        flash('สร้างประกาศใหม่สำเร็จ!', 'success')
        return redirect(url_for('stock.manage_announcements'))

    announcements = database.get_all_announcements(conn)
    return render_template('manage_announcements.html', announcements=announcements)

@bp.route('/update_announcement_status/<int:ann_id>', methods=['POST'])
@login_required
def update_announcement_status(ann_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ดำเนินการนี้', 'danger')
        # ไม่จำเป็นต้อง rollback ตรงนี้ เพราะยังไม่ได้เริ่มทำธุรกรรมกับ DB
        return redirect(url_for('stock.manage_announcements'))

    is_active = request.form.get('status') == 'true'
    conn = get_db()
    
    try:
        if is_active:
            # ทำให้ประกาศอื่นๆ ไม่ active ก่อน
            database.deactivate_all_announcements(conn)

        # อัปเดตสถานะของประกาศที่เลือก
        database.update_announcement_status(conn, ann_id, is_active)
        conn.commit()
        flash('อัปเดตสถานะประกาศสำเร็จ!', 'success')

    except Exception as e:
        conn.rollback() # <--- เพิ่ม conn.rollback() ในกรณีเกิดข้อผิดพลาด
        flash(f'เกิดข้อผิดพลาดในการอัปเดตสถานะ: {e}', 'danger')

    return redirect(url_for('stock.manage_announcements'))

@cache.memoize(timeout=900)
def get_cached_wholesale_summary(query=""):
    conn = get_db()
    return database.get_wholesale_customers_with_summary(conn, query=query)

@bp.route('/wholesale_dashboard')
@login_required
def wholesale_dashboard():
    if not (current_user.can_edit() or current_user.is_accountant()):
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))
    
    conn = get_db()
    
    # --- ✨ START: เพิ่ม List เดือนภาษาไทย ---
    THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    # --- END: ✨ สิ้นสุดส่วนที่เพิ่ม ---

    PER_PAGE = 20
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * PER_PAGE
    
    sort_by = request.args.get('sort_by', 'last_purchase_date')
    order = request.args.get('order', 'desc')

    search_query = request.args.get('search_query', '').strip()
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # (ส่วนของ try-except จัดการวันที่ยังคงเหมือนเดิม)
    try:
        if start_date_str: start_date_filter = datetime.strptime(start_date_str, '%Y-%m-%d')
        else: start_date_filter = get_bkk_time() - timedelta(days=29)
        if end_date_str: end_date_filter = datetime.strptime(end_date_str, '%Y-%m-%d')
        else: end_date_filter = get_bkk_time()
        start_date_filter = start_date_filter.replace(hour=0, minute=0, second=0)
        end_date_filter = end_date_filter.replace(hour=23, minute=59, second=59)
    except ValueError:
        flash("รูปแบบวันที่ไม่ถูกต้อง", "danger")
        end_date_filter = get_bkk_time()
        start_date_filter = end_date_filter - timedelta(days=29)

    total_customers = database.get_wholesale_customers_count(
        conn, 
        query=search_query,
        start_date=start_date_filter,
        end_date=end_date_filter
    )
    total_pages = (total_customers + PER_PAGE - 1) // PER_PAGE

    customers = database.get_wholesale_customers_with_summary(
        conn, 
        query=search_query, 
        start_date=start_date_filter, 
        end_date=end_date_filter,
        limit=PER_PAGE,
        offset=offset,
        sort_by=sort_by,
        order=order
    )
    
    today = get_bkk_time()

    return render_template('wholesale_dashboard.html', 
                           customers=customers, 
                           search_query=search_query,
                           start_date=start_date_filter.strftime('%Y-%m-%d'),
                           end_date=end_date_filter.strftime('%Y-%m-%d'),
                           current_user=current_user,
                           current_page=page,
                           total_pages=total_pages,
                           total_customers=total_customers,
                           today=today,
                           sort_by=sort_by,
                           order=order,
                           # --- ✨ ส่ง List เดือนไปที่ Template ---
                           THAI_MONTHS=THAI_MONTHS
                           )

@bp.route('/api/search_wholesale_customers')
@login_required
def api_search_wholesale_customers():
    # ... (permission check) ...
    conn = get_db()
    search_term = request.args.get('term', '').strip()
    if not search_term:
        return jsonify([])

    # เรียกใช้ฟังก์ชันใหม่ที่เบาและเร็วกว่ามาก
    customer_names = database.search_wholesale_customer_names(conn, search_term)

    return jsonify(customer_names)                           

@bp.route('/wholesale_customer/<int:customer_id>')
@login_required
def wholesale_customer_detail(customer_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()

    # --- START: ✨ ส่วนที่แก้ไข ---
    
    # 1. ดึงข้อมูลสรุปยอดรวมทั้งหมด (แยกตามประเภท) จากฟังก์ชันใหม่
    customer_summary = database.get_wholesale_customer_details_with_breakdown(conn, customer_id)
    if not customer_summary:
        flash(f"ไม่พบข้อมูลลูกค้า ID: {customer_id}", "danger")
        return redirect(url_for('stock.wholesale_dashboard'))

    # 2. จัดการเรื่องการกรองวันที่ (เหมือนเดิม)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not start_date_str or not end_date_str:
        today = get_bkk_time()
        end_date_obj = today.replace(hour=23, minute=59, second=59)
        start_date_obj = today.replace(day=1, hour=0, minute=0, second=0)
    else:
        try:
            start_date_obj = BKK_TZ.localize(datetime.strptime(start_date_str, '%Y-%m-%d')).replace(hour=0, minute=0, second=0)
            end_date_obj = BKK_TZ.localize(datetime.strptime(end_date_str, '%Y-%m-%d')).replace(hour=23, minute=59, second=59)
        except (ValueError, TypeError):
            flash("รูปแบบวันที่ไม่ถูกต้อง", "warning")
            end_date_obj = get_bkk_time()
            start_date_obj = end_date_obj - timedelta(days=30)

    # 3. ดึงประวัติการซื้อทั้งหมดในช่วงวันที่ที่เลือก
    history_all = database.get_wholesale_customer_purchase_history(conn, customer_id, start_date=start_date_obj, end_date=end_date_obj)

    # 4. แยกประวัติออกเป็น 3 list สำหรับแต่ละ Tab
    tire_history = [item for item in history_all if item['item_type'] == 'tire']
    wheel_history = [item for item in history_all if item['item_type'] == 'wheel']
    spare_part_history = [item for item in history_all if item['item_type'] == 'spare_part']

    # --- END: ✨ สิ้นสุดส่วนที่แก้ไข ---

    return render_template('wholesale_customer_detail.html',
                           customer_summary=customer_summary, # <--- ส่งข้อมูลสรุปใหม่
                           tire_history=tire_history,         # <--- ส่งประวัติยาง
                           wheel_history=wheel_history,       # <--- ส่งประวัติแม็ก
                           spare_part_history=spare_part_history, # <--- ส่งประวัติอะไหล่
                           start_date_param=start_date_obj.strftime('%Y-%m-%d'),
                           end_date_param=end_date_obj.strftime('%Y-%m-%d'),
                           current_user=current_user)


@bp.route('/view_activity_logs')
@login_required
def view_activity_logs():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    
    page = request.args.get('page', 1, type=int)
    per_page = 50

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    user_id_filter = request.args.get('user_id', type=int)
    method_filter = request.args.get('method')

    start_date = None
    if start_date_str:
        start_date = BKK_TZ.localize(datetime.strptime(start_date_str, '%Y-%m-%d')).replace(hour=0, minute=0, second=0).isoformat()
    
    end_date = None
    if end_date_str:
        end_date = BKK_TZ.localize(datetime.strptime(end_date_str, '%Y-%m-%d')).replace(hour=23, minute=59, second=59).isoformat()

    logs_raw = database.get_activity_logs(conn, limit=per_page, page=page, 
                                     start_date=start_date, end_date=end_date,
                                     user_id=user_id_filter, method=method_filter)
    
    # --- START: ส่วนที่เพิ่มเข้ามา ---
    # พจนานุกรมสำหรับแปลชื่อ Endpoint
    ENDPOINT_TRANSLATIONS = {
        'stock.index': 'ดูภาพรวมสต็อก',
        'stock.add_item': 'เพิ่มสินค้า',
        'stock.stock_movement': 'ทำรายการรับเข้า/จ่ายออก',
        'stock.barcode_scanner_page': 'เข้าหน้าสแกนบาร์โค้ด',
        'stock.daily_stock_report': 'ดูรายงานสต็อกประจำวัน',
        'stock.summary_stock_report': 'ดูสรุปยอดแบบละเอียด',
        'stock.reconciliation': 'ปิดยอดสต็อกประจำวัน',
        'stock.sales_history_search': 'ค้นหาประวัติการขาย',
        'stock.commission_summary_report': 'ดูรายงานคอมมิชชั่น',
        'stock.product_analysis': 'ดูหน้าวิเคราะห์สินค้า',
        'stock.wholesale_dashboard': 'ดูลูกค้าค้าส่ง',
        'stock.admin_dashboard': 'เข้าหน้า Admin Dashboard',
        'stock.edit_tire': 'แก้ไขข้อมูลยาง',
        'stock.edit_wheel': 'แก้ไขข้อมูลแม็ก',
        'stock.edit_spare_part': 'แก้ไขข้อมูลอะไหล่',
        'stock.delete_tire': 'ลบข้อมูลยาง',
        'stock.delete_wheel': 'ลบข้อมูลแม็ก',
        'stock.delete_spare_part': 'ลบข้อมูลอะไหล่',
        'stock.manage_users': 'จัดการผู้ใช้งาน',
        'stock.manage_announcements': 'จัดการประกาศ',
        'stock.view_activity_logs': 'ดูประวัติการใช้งาน',
        'stock.bulk_stock_movement': 'ทำรายการรับเข้า/จ่ายออกแบบชุด',
        'stock.add_spare_part_category': 'เพิ่มหมวดหมู่อะไหล่',
        'stock.manage_daily_commission': 'จัดการค่าคอมมิชชันหน้าร้าน',
        'stock.add_new_user': 'เพิ่มผู้ใช้ใหม่',
        'auth.login': 'เข้าสู่ระบบ',
        'auth.logout': 'ออกจากระบบ',
        'service.index': 'เข้าสู่โมดูล Service',
        'service.jobs_list': 'ดูรายการใบงาน',
        'service.create_job': 'สร้างใบงานใหม่',
        'service.edit_job': 'แก้ไขใบงาน'
    }

    logs_processed = []
    for log_row in logs_raw:
        log_dict = dict(log_row)
        # ใช้ .get() เพื่อหาคำแปล, ถ้าไม่เจอให้ใช้ชื่อเดิม
        log_dict['friendly_endpoint'] = ENDPOINT_TRANSLATIONS.get(log_dict['endpoint'], log_dict['endpoint'])
        logs_processed.append(log_dict)
    # --- END: ส่วนที่เพิ่มเข้ามา ---
    
    total_logs = database.get_activity_logs_count(conn, start_date, end_date, user_id_filter, method_filter)
    total_pages = (total_logs + per_page - 1) // per_page
    
    all_users = database.get_all_users_for_assignment(conn)

    return render_template('view_activity_logs.html', 
                           logs=logs_processed, # <<< ส่งข้อมูลที่ผ่านการแปลแล้ว
                           all_users=all_users,
                           current_page=page,
                           total_pages=total_pages,
                           start_date_filter=start_date_str,
                           end_date_filter=end_date_str,
                           user_id_filter=user_id_filter,
                           method_filter=method_filter
                           )

# แทนที่ฟังก์ชัน reconciliation ของเดิมทั้งหมดด้วยอันนี้
@bp.route('/reconciliation', methods=['GET', 'POST'])
@login_required
def reconciliation():
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()

    report_date_str = request.args.get('date')
    try:
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date() if report_date_str else get_bkk_time().date()
    except (ValueError, TypeError):
        flash("รูปแบบวันที่ไม่ถูกต้อง, ใช้ YYYY-MM-DD", "danger")
        conn.rollback()
        report_date = get_bkk_time().date()

    if request.method == 'POST':
        rec_id = request.form.get('reconciliation_id')
        ledger_data_json = request.form.get('manager_ledger_data')
        if rec_id and ledger_data_json:
            try:
                ledger_data = json.loads(ledger_data_json)
                database.update_manager_ledger(conn, rec_id, ledger_data)
                conn.commit()
                flash('บันทึกข้อมูลในสมุดกระทบยอดสำเร็จ!', 'success')
            except Exception as e:
                import traceback
                print("\n--- !!! AN ERROR OCCURRED DURING SAVE !!! ---")
                traceback.print_exc()
                print("---------------------------------------------\n")
                conn.rollback()
                flash(f'เกิดข้อผิดพลาดในการบันทึก: {e}', 'danger')
        else:
            flash('ข้อมูลไม่ครบถ้วน ไม่สามารถบันทึกได้', 'warning')
        return redirect(url_for('stock.reconciliation', date=report_date.strftime('%Y-%m-%d')))

    try:
        reconciliation_record = database.get_or_create_reconciliation_for_date(conn, report_date, current_user.id)
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"เกิดข้อผิดพลาดในการสร้างหรือดึงข้อมูลกระทบยอด: {e}", "danger")
        return redirect(url_for('stock.index'))

    # --- UPGRADED QUERIES ---
    is_psycopg2_conn = "psycopg2" in str(type(conn))
    sql_date_filter = report_date.strftime('%Y-%m-%d')
    placeholder = "%s" if is_psycopg2_conn else "?"

    wheel_size_concat = "(w.diameter || 'x' || w.width || ' ' || w.pcd)"
    if is_psycopg2_conn:
        wheel_size_concat = "CONCAT(w.diameter, 'x', w.width, ' ', w.pcd)"

    # --- UPGRADED TIRE QUERY ---
    tire_movements_query = f"""
        SELECT 'tire' as item_type, tm.id, tm.tire_id, tm.type, tm.quantity_change,
               t.brand, t.model, t.size, u.username,
               sc.name as channel_name, op.name as online_platform_name, wc.name as wholesale_customer_name,
               tm.channel_id, tm.online_platform_id, tm.wholesale_customer_id, tm.return_customer_type
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        LEFT JOIN users u ON tm.user_id = u.id
        LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
        LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
        WHERE {database.get_sql_date_format_for_query('tm.timestamp')} = {placeholder}
        ORDER BY tm.timestamp DESC
    """

    # --- UPGRADED WHEEL QUERY ---
    wheel_movements_query = f"""
        SELECT 'wheel' as item_type, wm.id, wm.wheel_id, wm.type, wm.quantity_change,
               w.brand, w.model, {wheel_size_concat} as size, u.username,
               sc.name as channel_name, op.name as online_platform_name, wc.name as wholesale_customer_name,
               wm.channel_id, wm.online_platform_id, wm.wholesale_customer_id, wm.return_customer_type
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        LEFT JOIN users u ON wm.user_id = u.id
        LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
        LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
        WHERE {database.get_sql_date_format_for_query('wm.timestamp')} = {placeholder}
        ORDER BY wm.timestamp DESC
    """

    # NEW: Spare Part Movements Query
    spare_part_movements_query = f"""
        SELECT 'spare_part' as item_type, spm.id, spm.spare_part_id, spm.type, spm.quantity_change,
               sp.name AS brand, sp.part_number AS model, sp.brand AS size, u.username,
               sc.name as channel_name, op.name as online_platform_name, wc.name as wholesale_customer_name,
               spm.channel_id, spm.online_platform_id, spm.wholesale_customer_id, spm.return_customer_type
        FROM spare_part_movements spm
        JOIN spare_parts sp ON spm.spare_part_id = sp.id
        LEFT JOIN users u ON spm.user_id = u.id
        LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
        LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
        LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
        WHERE {database.get_sql_date_format_for_query('spm.timestamp')} = {placeholder}
        ORDER BY spm.timestamp DESC
    """

    try:
        cursor = conn.cursor()
        cursor.execute(tire_movements_query, (sql_date_filter,))
        tire_movements = cursor.fetchall()
        cursor.execute(wheel_movements_query, (sql_date_filter,))
        wheel_movements = cursor.fetchall()
        cursor.execute(spare_part_movements_query, (sql_date_filter,)) # NEW
        spare_part_movements = cursor.fetchall() # NEW
        cursor.close()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลเคลื่อนไหว: {e}", "danger")
        conn.rollback()
        tire_movements, wheel_movements, spare_part_movements = [], [], [] # NEW

    system_movements = [dict(m) for m in tire_movements] + [dict(m) for m in wheel_movements] + [dict(m) for m in spare_part_movements] # NEW

    # ดึงข้อมูล Master ทั้งหมดสำหรับใช้ใน Dropdown ของ Pop-up
    all_sales_channels = get_all_sales_channels_cached()
    all_online_platforms = get_all_online_platforms_cached()
    all_wholesale_customers = get_all_wholesale_customers_cached()

    return render_template('reconciliation.html',
                            report_date=report_date,
                            reconciliation_record=reconciliation_record,
                            system_movements=system_movements,
                            all_sales_channels=all_sales_channels,
                            all_online_platforms=all_online_platforms,
                            all_wholesale_customers=all_wholesale_customers,
                            current_user=current_user)

# --- เพิ่ม 2 API ใหม่นี้เข้าไป ---
@bp.route('/api/get_movement_details')
@login_required
def api_get_movement_details():
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    item_type = request.args.get('item_type')
    movement_id = request.args.get('movement_id', type=int)

    if not item_type or not movement_id:
        return jsonify({"success": False, "message": "Missing parameters"}), 400

    conn = get_db()
    movement_details = None
    if item_type == 'tire':
        movement_details = database.get_tire_movement(conn, movement_id)
    elif item_type == 'wheel':
        movement_details = database.get_wheel_movement(conn, movement_id)
    elif item_type == 'spare_part': # NEW
        movement_details = database.get_spare_part_movement(conn, movement_id)

    if movement_details:
        return jsonify({"success": True, "details": dict(movement_details)})
    else:
        return jsonify({"success": False, "message": "Movement not found"}), 404

@bp.route('/api/correct_movement', methods=['POST'])
@login_required
def api_correct_movement():
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    data = request.json
    item_type = data.get('item_type')
    movement_id = data.get('movement_id')

    try:
        conn = get_db()
        if item_type == 'tire':
            database.update_tire_movement(
                conn, movement_id,
                new_notes=data.get('notes'),
                new_image_filename=data.get('image_filename'), # This will be the old one as we don't upload new image here
                new_type=data.get('type'),
                new_quantity_change=int(data.get('quantity_change')),
                new_channel_id=int(data.get('channel_id')) if data.get('channel_id') else None,
                new_online_platform_id=int(data.get('online_platform_id')) if data.get('online_platform_id') else None,
                new_wholesale_customer_id=int(data.get('wholesale_customer_id')) if data.get('wholesale_customer_id') else None,
                new_return_customer_type=data.get('return_customer_type')
            )
        elif item_type == 'wheel':
             database.update_wheel_movement(
                conn, movement_id,
                new_notes=data.get('notes'),
                new_image_filename=data.get('image_filename'),
                new_type=data.get('type'),
                new_quantity_change=int(data.get('quantity_change')),
                new_channel_id=int(data.get('channel_id')) if data.get('channel_id') else None,
                new_online_platform_id=int(data.get('online_platform_id')) if data.get('online_platform_id') else None,
                new_wholesale_customer_id=int(data.get('wholesale_customer_id')) if data.get('wholesale_customer_id') else None,
                new_return_customer_type=data.get('return_customer_type')
            )
        elif item_type == 'spare_part': # NEW
             database.update_spare_part_movement(
                conn, movement_id,
                new_notes=data.get('notes'),
                new_image_filename=data.get('image_filename'),
                new_type=data.get('type'),
                new_quantity_change=int(data.get('quantity_change')),
                new_channel_id=int(data.get('channel_id')) if data.get('channel_id') else None,
                new_online_platform_id=int(data.get('online_platform_id')) if data.get('online_platform_id') else None,
                new_wholesale_customer_id=int(data.get('wholesale_customer_id')) if data.get('wholesale_customer_id') else None,
                new_return_customer_type=data.get('return_customer_type')
            )
        conn.commit()
        if item_type == 'tire':
            cache.delete_memoized(get_all_tires_list_cached)
        elif item_type == 'wheel':
            cache.delete_memoized(get_all_wheels_list_cached)
        elif item_type == 'spare_part':
            cache.delete_memoized(get_all_spare_parts_cached)
        return jsonify({"success": True, "message": "แก้ไขรายการสำเร็จ!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@bp.route('/reconciliation/complete/<int:rec_id>', methods=['POST'])
@login_required
def complete_reconciliation_action(rec_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการดำเนินการนี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    try:
        # 1. สั่งให้ database ทำการ UPDATE
        database.complete_reconciliation(conn, rec_id)
        
        # 2. ยืนยันการเปลี่ยนแปลงลงฐานข้อมูล
        conn.commit()
        print(f"DEBUG: Transaction for rec_id {rec_id} has been committed.")

        # ----- 3. ขั้นตอนการตรวจสอบ (VERIFICATION STEP) -----
        # ดึงข้อมูลจากฐานข้อมูลอีกครั้ง *หลัง* จาก commit เพื่อตรวจสอบว่าค่าเปลี่ยนจริงหรือไม่
        verified_rec = database.get_reconciliation_by_id(conn, rec_id)
        
        if verified_rec and verified_rec['status'] == 'completed':
            # ถ้าสถานะเปลี่ยนเป็น completed จริงๆ แสดงว่าทุกอย่างสำเร็จ
            flash('ปิดการกระทบยอดสำหรับวันนี้เรียบร้อยแล้ว!', 'success')
        else:
            # ถ้าสถานะไม่เปลี่ยน แสดงว่าการ commit ไม่ได้ผล
            status = verified_rec['status'] if verified_rec else 'Not Found'
            flash('เกิดข้อผิดพลาด: การอัปเดตสถานะไม่สำเร็จหลังจากการ commit', 'danger')
            conn.rollback()
            print(f"CRITICAL: Commit for rec_id {rec_id} did not persist! Status is still: {status}")
        
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดในการปิดการกระทบยอด: {e}', 'danger')
        print(f"ERROR: Exception during complete_reconciliation_action: {e}")

    # --- ส่วนของการ Redirect ยังคงเหมือนเดิม ---
    rec = database.get_reconciliation_by_id(conn, rec_id)
    date_str = ''
    if rec:
        date_value = rec['reconciliation_date']
        if isinstance(date_value, str):
            date_obj = datetime.strptime(date_value, '%Y-%m-%d').date()
        else:
            date_obj = date_value
        date_str = date_obj.strftime('%Y-%m-%d')

    return redirect(url_for('stock.reconciliation', date=date_str))

# แทนที่ api_search_all_items ของเดิมด้วยอันนี้
@bp.route('/api/search_all_items')
@login_required
def api_search_all_items():
    query = request.args.get('q', '').strip()
    # current_app.logger.debug(f"API Search All Items - Received query: '{query}'") # DEBUG
    if not query:
        # current_app.logger.debug("API Search All Items - Empty query, returning empty results.") # DEBUG
        return jsonify({'results': []})

    conn = get_db()
    search_term = f"%{query.lower()}%"
    # current_app.logger.debug(f"API Search All Items - Search term: '{search_term}'") # DEBUG

    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"
    like_op = "ILIKE" if is_postgres else "LIKE"

    # For PostgreSQL, CONCAT is standard. For SQLite, use ||
    # COALESCE handles NULL values, replacing them with empty strings for concatenation
    wheel_size_search_col_sql = f"LOWER(COALESCE(w.diameter, '') || 'x' || COALESCE(w.width, '') || ' ' || COALESCE(w.pcd, '') || ' ET' || COALESCE(w.et, '') || ' ' || COALESCE(w.color, ''))"
    if is_postgres:
        wheel_size_search_col_sql = f"LOWER(CONCAT(w.diameter::TEXT, 'x', w.width::TEXT, ' ', COALESCE(w.pcd, ''), ' ET', COALESCE(w.et::TEXT, ''), ' ', COALESCE(w.color, '')))"


    tire_query = f"""
        SELECT t.id, t.brand, t.model, t.size, t.quantity AS current_quantity, 'tire' as item_type_str
        FROM tires t
        WHERE t.is_deleted = { 'FALSE' if is_postgres else '0' }
        AND (LOWER(t.brand) {like_op} {placeholder} OR LOWER(t.model) {like_op} {placeholder} OR LOWER(t.size) {like_op} {placeholder})
        LIMIT 30
    """

    # For wheels, explicitly select all relevant columns for formatting in Python
    wheel_query = f"""
        SELECT w.id, w.brand, w.model, w.diameter, w.pcd, w.width, w.et, w.color, w.quantity AS current_quantity, 'wheel' as item_type_str
        FROM wheels w
        WHERE w.is_deleted = { 'FALSE' if is_postgres else '0' }
        AND (LOWER(w.brand) {like_op} {placeholder} OR LOWER(w.model) {like_op} {placeholder} OR LOWER(w.pcd) {like_op} {placeholder} OR {wheel_size_search_col_sql} {like_op} {placeholder})
        LIMIT 30
    """

    # For spare parts, select all relevant original column names
    spare_part_query = f"""
        SELECT sp.id, sp.name, sp.part_number, sp.brand, sp.quantity AS current_quantity, 'spare_part' as item_type_str
        FROM spare_parts sp
        WHERE sp.is_deleted = { 'FALSE' if is_postgres else '0' }
        AND (LOWER(sp.name) {like_op} {placeholder} OR LOWER(sp.part_number) {like_op} {placeholder} OR LOWER(sp.brand) {like_op} {placeholder})
        LIMIT 30
    """

    results_raw = []
    try:
        cursor = conn.cursor()

        cursor.execute(tire_query, (search_term, search_term, search_term))
        results_raw.extend([dict(row) for row in cursor.fetchall()])
        # current_app.logger.debug(f"API Search All Items - Tire results count: {len(results_raw) - len(results_raw_before_tire)}") # DEBUG

        results_raw_before_wheel = len(results_raw)
        cursor.execute(wheel_query, (search_term, search_term, search_term, search_term))
        results_raw.extend([dict(row) for row in cursor.fetchall()])
        # current_app.logger.debug(f"API Search All Items - Wheel results count: {len(results_raw) - results_raw_before_wheel}") # DEBUG

        results_raw_before_spare_part = len(results_raw)
        cursor.execute(spare_part_query, (search_term, search_term, search_term))
        results_raw.extend([dict(row) for row in cursor.fetchall()])
        # current_app.logger.debug(f"API Search All Items - Spare Part results count: {len(results_raw) - results_raw_before_spare_part}") # DEBUG

        cursor.close()

        formatted_results = []
        for item in results_raw:
            item_id_prefix = item['item_type_str']
            display_text = ""

            if item_id_prefix == 'tire':
                display_text = f"[{item_id_prefix.upper()}] {item.get('brand', '').title()} {item.get('model', '').title()} - {item.get('size', '')}"
            elif item_id_prefix == 'wheel':
                # Safely get all relevant wheel properties
                wheel_brand = item.get('brand', '').title()
                wheel_model = item.get('model', '').title()
                wheel_diameter = item.get('diameter')
                wheel_width = item.get('width')
                wheel_pcd = item.get('pcd')
                wheel_et = item.get('et')
                wheel_color = item.get('color')

                wheel_spec_parts = []
                if wheel_diameter is not None and wheel_width is not None:
                    wheel_spec_parts.append(f"{float(wheel_diameter):.0f}x{float(wheel_width):.0f}") # Format as whole numbers if possible
                if wheel_pcd:
                    wheel_spec_parts.append(wheel_pcd)
                if wheel_et is not None:
                    wheel_spec_parts.append(f"ET{int(wheel_et)}") # Format as integer if possible
                if wheel_color:
                    wheel_spec_parts.append(f"สี:{wheel_color}")

                wheel_spec = " ".join(wheel_spec_parts).strip()
                if wheel_spec:
                    display_text = f"[{item_id_prefix.upper()}] {wheel_brand} {wheel_model} - {wheel_spec}"
                else:
                    display_text = f"[{item_id_prefix.upper()}] {wheel_brand} {wheel_model}"

            elif item_id_prefix == 'spare_part':
                part_name = item.get('name', '')
                part_number = item.get('part_number', '') # Use .get()
                part_brand = item.get('brand', '') # Use .get()

                part_display_parts = []
                if part_name:
                    part_display_parts.append(part_name)
                if part_number:
                    part_display_parts.append(f"(Part No: {part_number})")
                if part_brand:
                    part_display_parts.append(f"ยี่ห้อ: {part_brand.title()}")

                display_text = f"[{item_id_prefix.upper()}] {' '.join(part_display_parts).strip()}"

            formatted_results.append({
                "id": f"{item_id_prefix}-{item['id']}",
                "text": display_text,
                "data": item # Pass the full item data for client-side reference if needed
            })

        # current_app.logger.debug(f"API Search All Items - Total formatted results: {len(formatted_results)}") # DEBUG
        return jsonify({"results": formatted_results}) # Select2 v4.1+ expects { results: [...] }

    except Exception as e:
        current_app.logger.error(f"Error in api_search_all_items: {e}", exc_info=True) # Log full traceback
        return jsonify({'results': []})

    # --- END: ส่วนที่แก้ไข ---

    # Format results for Select2 (or similar dropdowns)
    formatted_results = []
    for item in results:
        if item['type'] == 'tire':
            formatted_results.append({
                "id": f"tire-{item['id']}",
                "text": f"[{item['type'].upper()}] {item['brand'].title()} {item['model'].title()} - {item['size']}"
            })
        elif item['type'] == 'wheel':
            formatted_results.append({
                "id": f"wheel-{item['id']}",
                "text": f"[{item['type'].upper()}] {item['brand'].title()} {item['model'].title()} - {item['size']}"
            })
        elif item['type'] == 'spare_part': # NEW
            display_name = item['name']
            if item['part_number']:
                display_name += f" (Part No: {item['part_number']})"
            if item['brand']:
                display_name += f" ยี่ห้อ: {item['brand'].title()}"
            formatted_results.append({
                "id": f"spare_part-{item['id']}",
                "text": f"[{item['type'].upper()}] {display_name}"
            })

    return jsonify({"results": formatted_results}) # Select2 v4.1+ สามารถรับ array ได้โดยตรง

@bp.route('/api/process_data', methods=['POST'])
def process_data():
    data = request.get_json()

    # ใช้ .get() เพื่อดึงค่า ถ้าไม่มี key นั้นอยู่ จะได้ค่า default เป็น None (ซึ่ง JSON serialize ได้)
    notes_from_request = data.get('notes', None)

    processed_data = {
        'id': data.get('id'), # ควรใช้ .get() กับทุก key ที่ไม่แน่ใจ
        'status': 'processed',
        'notes': notes_from_request 
    }
    
    return jsonify(processed_data)

# --- Spare Part Categories Management Routes (NEW SECTION) ---
@bp.route('/manage_spare_part_categories')
@login_required
def manage_spare_part_categories():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการจัดการหมวดหมู่อะไหล่', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    categories_hierarchical = database.get_all_spare_part_categories_hierarchical(conn)

    return render_template('manage_spare_part_categories.html',
                           categories=categories_hierarchical,
                           all_categories_flat=categories_hierarchical, # ส่งตัวแปรเดียวกัน
                           current_user=current_user)

@bp.route('/add_spare_part_category', methods=['POST'])
@login_required
def add_spare_part_category():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการเพิ่มหมวดหมู่อะไหล่', 'danger')
        return redirect(url_for('stock.manage_spare_part_categories'))

    category_name = request.form.get('name', '').strip()
    parent_id_str = request.form.get('parent_id')

    if not category_name:
        flash('กรุณากรอกชื่อหมวดหมู่', 'danger')
        # ไม่ต้อง rollback ตรงนี้เพราะยังไม่ได้เชื่อมต่อ DB
        return redirect(url_for('stock.manage_spare_part_categories'))

    parent_id = int(parent_id_str) if parent_id_str and parent_id_str != 'none' else None

    conn = get_db()
    try:
        database.add_spare_part_category(conn, category_name, parent_id)
        conn.commit()
        flash(f'เพิ่มหมวดหมู่ "{category_name}" สำเร็จ!', 'success')
        cache.delete_memoized(get_cached_spare_part_categories_hierarchical)
        # No need to clear spare_parts cache, as new category doesn't change existing parts
    except ValueError as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาด: {e}', 'danger')
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดในการเพิ่มหมวดหมู่: {e}', 'danger')

    return redirect(url_for('stock.manage_spare_part_categories'))


@bp.route('/edit_spare_part_category/<int:category_id>', methods=['GET', 'POST'])
@login_required
def edit_spare_part_category(category_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขหมวดหมู่อะไหล่', 'danger')
        return redirect(url_for('stock.manage_spare_part_categories'))

    conn = get_db()
    category = database.get_spare_part_category(conn, category_id)
    # ✅ FIX: ใช้ list แบบมีลำดับชั้นสำหรับ dropdown เพื่อให้แสดงผลสอดคล้องกัน
    all_categories_hierarchical = database.get_all_spare_part_categories_hierarchical(conn)

    if category is None:
        flash('ไม่พบหมวดหมู่ที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.manage_spare_part_categories'))

    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        new_parent_id_str = request.form.get('parent_id')

        if not new_name:
            flash('กรุณากรอกชื่อหมวดหมู่', 'danger')
            conn.rollback()
            return render_template('add_edit_spare_part_category.html', category=category, all_categories_flat=all_categories_hierarchical, current_user=current_user)

        new_parent_id = int(new_parent_id_str) if new_parent_id_str and new_parent_id_str != 'none' else None

        try:
            database.update_spare_part_category(conn, category_id, new_name, new_parent_id)
            conn.commit()
            flash(f'แก้ไขหมวดหมู่ "{new_name}" สำเร็จ!', 'success')
            cache.delete_memoized(get_cached_spare_part_categories_hierarchical)
            cache.delete_memoized(get_all_spare_parts_cached)
        except ValueError as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาด: {e}', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาดในการแก้ไขหมวดหมู่: {e}', 'danger')

        return redirect(url_for('stock.manage_spare_part_categories'))

    return render_template('add_edit_spare_part_category.html',
                           category=category,
                           all_categories_flat=all_categories_hierarchical,
                           current_user=current_user)

@bp.route('/delete_spare_part_category/<int:category_id>', methods=['POST'])
@login_required
def delete_spare_part_category(category_id):
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการลบหมวดหมู่อะไหล่', 'danger')
        return redirect(url_for('stock.manage_spare_part_categories'))

    conn = get_db()
    try:
        database.delete_spare_part_category(conn, category_id)
        conn.commit()
        flash('ลบหมวดหมู่สำเร็จ!', 'success')
        cache.delete_memoized(get_cached_spare_part_categories_hierarchical)
        cache.delete_memoized(get_all_spare_parts_cached)
        cache.delete_memoized(get_cached_spare_parts)
    except ValueError as e:
        conn.rollback()
        flash(f'ไม่สามารถลบหมวดหมู่ได้: {e}', 'danger')
        conn.rollback()
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดในการลบหมวดหมู่: {e}', 'danger')
        conn.rollback()

    return redirect(url_for('stock.manage_spare_part_categories'))

@bp.route('/print_barcodes/<item_type>/<int:item_id>', methods=['GET', 'POST'])
@login_required
def print_barcodes(item_type, item_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการพิมพ์บาร์โค้ด', 'danger')
        return redirect(request.referrer or url_for('index'))

    conn = get_db()
    item_info = {}
    barcode_strings_all = []

    # ⭐️ แก้ไขตรงนี้: แปลงแต่ละ Row object ใน presets ให้เป็น dictionary ก่อนส่งไป template
    raw_presets = database.get_all_label_presets(conn) # ดึงข้อมูลดิบ
    presets = [dict(row) for row in raw_presets] # แปลงเป็น list ของ dictionary

    try:
        item = None
        if item_type == 'tire':
            item = database.get_tire(conn, item_id)
            if not item: raise ValueError("ไม่พบยางที่ระบุ")
            barcode_strings_all = [bc['barcode_string'] for bc in database.get_barcodes_for_tire(conn, item_id)]
            item_info = {
                'name': f"{item['brand'].title()} {item['model'].title()} {item['size']}",
                'price': item.get('price_per_item'),
                'type': item_type,
                'id': item_id
            }
        elif item_type == 'wheel':
            item = database.get_wheel(conn, item_id)
            if not item: raise ValueError("ไม่พบแม็กที่ระบุ")
            barcode_strings_all = [bc['barcode_string'] for bc in database.get_barcodes_for_wheel(conn, item_id)]
            item_info = {
                'name': f"{item['brand'].title()} {item['model'].title()} {item['pcd']}",
                'price': item.get('retail_price'),
                'type': item_type,
                'id': item_id
            }
        elif item_type == 'spare_part':
            item = database.get_spare_part(conn, item_id)
            if not item: raise ValueError("ไม่พบอะไหล่ที่ระบุ")
            barcode_strings_all = [bc['barcode_string'] for bc in database.get_barcodes_for_spare_part(conn, item_id)]
            item_info = {
                'name': f"{item['name']} ({item.get('part_number', '')})",
                'price': item.get('retail_price'),
                'type': item_type,
                'id': item_id
            }
        else:
            raise ValueError("ประเภทสินค้าไม่ถูกต้อง")

        if not barcode_strings_all:
            flash('สินค้านี้ยังไม่มีรหัสบาร์โค้ดให้พิมพ์', 'warning')
            return redirect(request.referrer or url_for('index'))

        if request.method == 'POST':
            selected_barcodes = request.form.getlist('selected_barcodes')
            if not selected_barcodes:
                flash('กรุณาเลือกบาร์โค้ดที่ต้องการพิมพ์อย่างน้อยหนึ่งรหัส', 'danger')
                conn.rollback()
                return render_template('print_barcodes.html',
                                       barcodes_all=barcode_strings_all,
                                       barcodes=[],
                                       item_info=item_info,
                                       presets=presets,
                                       is_printing=False)

            barcodes_data = [] # สร้างรายการสำหรับ SVG
            writer_options = {'module_height': 10.0, 'font_size': 10, 'text_distance': 3.0, 'quiet_zone': 2.0}
            for bc_string in selected_barcodes:
                code128 = barcode.get('code128', bc_string, writer=SVGWriter())
                svg_buffer_barcode = BytesIO()
                code128.write(svg_buffer_barcode, options=writer_options)
                svg_string_barcode = svg_buffer_barcode.getvalue().decode('utf-8')

                qr_img = qrcode.make(bc_string, image_factory=qrcode.image.svg.SvgPathImage, box_size=20)
                svg_buffer_qr = BytesIO()
                qr_img.save(svg_buffer_qr)
                svg_string_qrcode = svg_buffer_qr.getvalue().decode('utf-8')

                barcodes_data.append({
                    'svg_barcode': svg_string_barcode,
                    'svg_qrcode': svg_string_qrcode,
                    'text': bc_string
                })

            return render_template('print_barcodes.html',
                                   barcodes_all=barcode_strings_all,
                                   barcodes=barcodes_data,
                                   item_info=item_info,
                                   presets=presets,
                                   is_printing=True)

    except ValueError as e:
        flash(str(e), 'danger')
        conn.rollback()
        return redirect(request.referrer or url_for('index'))

    # สำหรับ GET request (แสดงหน้าเลือก)
    return render_template('print_barcodes.html',
                           barcodes_all=barcode_strings_all,
                           barcodes=[],
                           item_info=item_info,
                           presets=presets,
                           is_printing=False)

def add_tire_cost_history(conn, tire_id, old_cost, new_cost, user_id, notes=""):
    """บันทึกการเปลี่ยนแปลงราคาทุนของยาง"""
    changed_at = get_bkk_time().isoformat()
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    
    query = "INSERT INTO tire_cost_history (tire_id, changed_at, old_cost_sc, new_cost_sc, user_id, notes) VALUES (?, ?, ?, ?, ?, ?)"
    params = (tire_id, changed_at, old_cost, new_cost, user_id, notes)

    if is_postgres:
        query = query.replace('?', '%s')

    cursor.execute(query, params)
    # ไม่ต้อง commit ที่นี่ เพราะจะถูกจัดการโดยฟังก์ชันที่เรียกใช้

def get_tire_cost_history(conn, tire_id):
    """ดึงประวัติการเปลี่ยนแปลงราคาทุนของยางที่ระบุ"""
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    
    query = """
        SELECT h.*, u.username
        FROM tire_cost_history h
        LEFT JOIN users u ON h.user_id = u.id
        WHERE h.tire_id = ?
        ORDER BY h.changed_at DESC
    """
    params = (tire_id,)
    
    if is_postgres:
        query = query.replace('?', '%s')
        
    cursor.execute(query, params)
    
    history = []
    for row in cursor.fetchall():
        history_item = dict(row)
        history_item['changed_at'] = convert_to_bkk_time(history_item['changed_at'])
        history.append(history_item)
        
    return history


@bp.route('/api/update_tire_cost', methods=['POST'])
@login_required
def api_update_tire_cost():
    # ตรวจสอบสิทธิ์: ต้องเป็น Admin หรือ Editor และต้องมีสิทธิ์ดูราคาทุน
    if not current_user.can_edit() or not current_user.can_view_cost():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการแก้ไขราคาทุน"}), 403

    data = request.get_json()
    tire_id = data.get('tire_id')
    cost_type = data.get('cost_type')
    new_cost = data.get('new_cost')

    # ตรวจสอบว่าข้อมูลที่ส่งมาครบถ้วน
    if not all([tire_id, cost_type]):
        return jsonify({"success": False, "message": "ข้อมูลไม่สมบูรณ์"}), 400

    # ตรวจสอบว่า cost_type เป็นค่าที่อนุญาตเพื่อป้องกัน SQL Injection
    allowed_cost_types = ['cost_sc', 'cost_dunlop', 'cost_online']
    if cost_type not in allowed_cost_types:
        return jsonify({"success": False, "message": "ประเภทของราคาทุนไม่ถูกต้อง"}), 400

    conn = get_db()
    try:
        # เรียกใช้ฟังก์ชันใหม่ใน database.py
        database.update_single_tire_cost(
            conn=conn,
            tire_id=tire_id,
            cost_type=cost_type,
            new_cost=new_cost,
            user_id=current_user.id
        )
        conn.commit()

        # เคลียร์ Cache ที่เกี่ยวข้องเพื่อให้ข้อมูลหน้าเว็บอัปเดต
        cache.delete_memoized(get_all_tires_list_cached)

        return jsonify({"success": True, "message": "อัปเดตราคาทุนสำเร็จ"})

    except ValueError as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 404
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error in api_update_tire_cost: {e}", exc_info=True)
        return jsonify({"success": False, "message": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"}), 500

@bp.route('/api/update_tire_price', methods=['POST'])
@login_required
def api_update_tire_price():
    # 1. ตรวจสอบสิทธิ์: ต้องเป็น Admin เท่านั้น
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการแก้ไขข้อมูลราคา (ต้องการสิทธิ์ Admin)"}), 403

    data = request.get_json()
    tire_id = data.get('tire_id')
    price_type = data.get('price_type')
    new_price = data.get('new_price')

    # 2. ตรวจสอบว่าข้อมูลที่ส่งมาครบถ้วน
    if not all([tire_id, price_type]):
        return jsonify({"success": False, "message": "ข้อมูลที่ส่งมาไม่สมบูรณ์"}), 400

    # 3. สร้าง Whitelist เพื่อความปลอดภัย ป้องกันการแก้ไขคอลัมน์อื่น
    allowed_price_types = ['wholesale_price1', 'wholesale_price2', 'price_per_item']
    if price_type not in allowed_price_types:
        return jsonify({"success": False, "message": "ประเภทของราคาไม่ถูกต้อง"}), 400

    conn = get_db()
    try:
        # 4. อัปเดตข้อมูลในฐานข้อมูล (เนื่องจากเช็ค is_admin() แล้ว จึงไม่จำเป็นต้องเช็คสิทธิ์รายคอลัมน์อีก)
        is_postgres = "psycopg2" in str(type(conn))
        placeholder = "%s" if is_postgres else "?"
        
        cursor = conn.cursor()
        
        # ตรวจสอบว่ายางมีอยู่จริงหรือไม่
        if is_postgres:
            cursor.execute("SELECT id FROM tires WHERE id = %s", (tire_id,))
        else:
            cursor.execute("SELECT id FROM tires WHERE id = ?", (tire_id,))

        if cursor.fetchone() is None:
            raise ValueError("ไม่พบยางที่ระบุ")

        # สร้างและ execute คำสั่ง SQL
        sql_update = f"UPDATE tires SET {price_type} = {placeholder} WHERE id = {placeholder}"
        cursor.execute(sql_update, (new_price, tire_id))
        
        conn.commit()

        # 5. เคลียร์ Cache เพื่อให้ข้อมูลหน้าเว็บอัปเดต
        cache.delete_memoized(get_all_tires_list_cached)

        return jsonify({"success": True, "message": "อัปเดตราคาสำเร็จ"})

    except ValueError as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 404
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error in api_update_tire_price: {e}", exc_info=True)
        return jsonify({"success": False, "message": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"}), 500

@bp.route('/api/get_item_details_for_modal')
@login_required
def api_get_item_details_for_modal():
    # ตรวจสอบสิทธิ์เบื้องต้นว่าผู้ใช้ login อยู่หรือไม่
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    item_type = request.args.get('item_type')
    item_id = request.args.get('item_id', type=int)

    if not item_type or not item_id:
        return jsonify({"success": False, "message": "ข้อมูลไม่ครบถ้วน"}), 400

    conn = get_db()
    item_details = None
    
    try:
        if item_type == 'tire':
            item_details = database.get_tire(conn, item_id)
        elif item_type == 'wheel':
            item_details = database.get_wheel(conn, item_id)
        elif item_type == 'spare_part':
            item_details = database.get_spare_part(conn, item_id)
        else:
            return jsonify({"success": False, "message": "ประเภทสินค้าไม่ถูกต้อง"}), 400

        if item_details:
            # แปลง Row object เป็น Dictionary เพื่อให้ jsonify ทำงานได้ถูกต้อง
            details_dict = dict(item_details)
            return jsonify({"success": True, "details": details_dict})
        else:
            return jsonify({"success": False, "message": "ไม่พบข้อมูลสินค้า"}), 404
            
    except Exception as e:
        current_app.logger.error(f"Error fetching item details for modal: {e}", exc_info=True)
        return jsonify({"success": False, "message": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"}), 500

@bp.route('/api/update_item_from_modal', methods=['POST'])
@login_required
def api_update_item_from_modal():
    # ตรวจสอบสิทธิ์: ต้องเป็น Admin หรือ Editor เท่านั้น
    if not current_user.can_edit():
        return jsonify({"success": False, "message": "คุณไม่มีสิทธิ์ในการแก้ไขข้อมูล"}), 403

    data = request.get_json()
    item_type = data.get('item_type')
    item_id = data.get('item_id')

    if not item_type or not item_id:
        return jsonify({"success": False, "message": "ข้อมูลไม่ครบถ้วน"}), 400

    conn = get_db()
    try:
        # --- Logic for Tire ---
        if item_type == 'tire':
            # ดึงข้อมูลเดิมเพื่อเปรียบเทียบราคาทุน
            old_tire_data = database.get_tire(conn, item_id)
            if not old_tire_data:
                raise ValueError("ไม่พบข้อมูลยางที่ต้องการแก้ไข")

            # รับค่าใหม่จากฟอร์มใน Modal
            new_brand = data.get('brand').strip().lower()
            new_model = data.get('model').strip().lower()
            new_size = data.get('size').strip()
            
            # แปลงค่าราคาทุน (จัดการกรณีที่ผู้ใช้ลบค่าออก)
            new_cost_sc = float(data['cost_sc']) if data.get('cost_sc') else None
            new_cost_dunlop = float(data['cost_dunlop']) if data.get('cost_dunlop') else None
            new_cost_online = float(data['cost_online']) if data.get('cost_online') else None

            # ตรวจสอบและบันทึกประวัติการเปลี่ยนแปลงราคาทุน
            if current_user.can_view_cost() and old_tire_data.get('cost_sc') != new_cost_sc:
                database.add_tire_cost_history(
                    conn=conn,
                    tire_id=item_id,
                    old_cost=old_tire_data.get('cost_sc'),
                    new_cost=new_cost_sc,
                    user_id=current_user.id,
                    notes="แก้ไขผ่าน Modal จากหน้า Stock Movement"
                )
            
            # อัปเดตข้อมูลยางทั้งหมด (ใช้ฟังก์ชันเดิม)
            database.update_tire(conn, item_id, new_brand, new_model, new_size,
                                 new_cost_sc, new_cost_dunlop, new_cost_online,
                                 old_tire_data['wholesale_price1'], old_tire_data['wholesale_price2'],
                                 old_tire_data['price_per_item'], old_tire_data['promotion_id'],
                                 old_tire_data['year_of_manufacture'])
            
            # เคลียร์ Cache ที่เกี่ยวข้อง
            cache.delete_memoized(get_cached_tire_brands)
            cache.delete_memoized(get_all_tires_list_cached)

        # --- Logic for Wheel (สามารถเพิ่มได้ในอนาคต) ---
        elif item_type == 'wheel':
            # (ใส่โค้ดสำหรับอัปเดตข้อมูลแม็กที่นี่)
            pass

        # --- Logic for Spare Part (สามารถเพิ่มได้ในอนาคต) ---
        elif item_type == 'spare_part':
            # (ใส่โค้ดสำหรับอัปเดตข้อมูลอะไหล่ที่นี่)
            pass
            
        else:
            raise ValueError("ประเภทสินค้าไม่ถูกต้อง")

        conn.commit()
        return jsonify({"success": True, "message": "บันทึกการเปลี่ยนแปลงสำเร็จ!"})

    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error in update_item_from_modal: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"เกิดข้อผิดพลาด: {str(e)}"}), 500

@bp.route('/manage_daily_commission', methods=['GET', 'POST'])
@login_required
def manage_daily_commission():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    
    if request.method == 'POST':
        # ... (ส่วนของ POST ไม่มีการแก้ไข) ...
        action = request.form.get('action')
        if action == 'set':
            try:
                item_identifier = request.form.get('item_select')
                amount = request.form.get('commission_amount', type=float)
                start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
                
                end_date_str = request.form.get('end_date')
                no_end_date = 'no_end_date' in request.form
                
                end_date = None
                if not no_end_date and end_date_str:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                    if end_date < start_date:
                        raise ValueError("วันที่สิ้นสุดต้องไม่น้อยกว่าวันที่เริ่มต้น")

                if item_identifier and amount is not None and amount >= 0:
                    item_type, item_id = item_identifier.split('-')
                    database.set_commission_program(conn, start_date, end_date, item_type, int(item_id), amount, current_user.id)
                    flash('ตั้งค่าโปรแกรมคอมมิชชั่นสำเร็จ!', 'success')
                    conn.commit()
                else:
                    flash('ข้อมูลไม่ครบถ้วนหรือไม่ถูกต้อง', 'danger')
                    conn.rollback()
            except ValueError as e:
                flash(str(e), 'danger')
                conn.rollback()

        elif action == 'delete':
            program_id = request.form.get('program_id', type=int)
            if program_id:
                database.delete_commission_program(conn, program_id)
                flash('ลบโปรแกรมคอมมิชชั่นสำเร็จ', 'success')
                conn.commit()

        return redirect(url_for('stock.manage_daily_commission'))
    
    # --- ส่วนที่แก้ไขสำหรับ GET request ---
    today = get_bkk_time().date()
    commission_programs_flat = database.get_commission_programs_for_date(conn, today)

    # จัดกลุ่มข้อมูลตามยี่ห้อ
    programs_by_brand = defaultdict(list)
    for prog in commission_programs_flat:
        brand_name = prog['brand'] or 'ไม่ระบุยี่ห้อ' # จัดการกรณีที่ brand เป็น None
        programs_by_brand[brand_name].append(prog)

    return render_template('manage_daily_commission.html',
                           programs_by_brand=programs_by_brand, # <--- ส่งตัวแปรใหม่ไปที่ Template
                           today_str=today.strftime('%Y-%m-%d'),
                           current_user=current_user)

@bp.route('/commission_summary_report', methods=['GET'])
@login_required
def commission_summary_report():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    
    start_date_str = request.args.get('start_date', get_bkk_time().replace(day=1).strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', get_bkk_time().strftime('%Y-%m-%d'))
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash("รูปแบบวันที่ไม่ถูกต้อง", "danger")
        start_date = get_bkk_time().replace(day=1).date()
        end_date = get_bkk_time().date()

    # --- START: ส่วนที่แก้ไขใหม่ทั้งหมด ---

    # 1. ดึงข้อมูลการขายแต่ละครั้งแบบละเอียด (เป็นข้อมูลหลักชุดเดียว)
    detailed_movements = database.get_commission_movements_by_period(conn, start_date, end_date)

    # 2. สร้างข้อมูลสรุป (summary_data) และข้อมูลจัดกลุ่ม (grouped_movements) จากข้อมูลหลักชุดเดียวกัน
    summary_map = {}
    grouped_movements = defaultdict(list)

    for movement in detailed_movements:
        desc = movement['item_description']
        
        # เพิ่มข้อมูลเข้าไปใน grouped_movements สำหรับแสดงรายละเอียด
        grouped_movements[desc].append(movement)
        
        # คำนวณยอดรวมเพื่อสร้าง summary_data
        if desc not in summary_map:
            summary_map[desc] = {
                'item_description': desc,
                'total_units_sold': 0,
                'total_commission': 0.0
            }
        
        summary_map[desc]['total_units_sold'] += movement['quantity_change']
        summary_map[desc]['total_commission'] += movement['commission_amount']

    # แปลง Map ของข้อมูลสรุปให้เป็น List และจัดเรียงตามยอดคอมมิชชั่น
    summary_data = sorted(summary_map.values(), key=lambda x: x['total_commission'], reverse=True)
    
    # --- END: ส่วนที่แก้ไขใหม่ทั้งหมด ---

    return render_template('commission_summary_report.html',
                           summary_data=summary_data,
                           grouped_movements=grouped_movements,
                           start_date_filter=start_date.strftime('%Y-%m-%d'),
                           end_date_filter=end_date.strftime('%Y-%m-%d'),
                           current_user=current_user)

@bp.route('/api/get_spare_part_categories')
@login_required
def api_get_spare_part_categories():
    """
    API Endpoint to get the latest hierarchical list of spare part categories.
    """
    try:
        # ใช้ฟังก์ชัน Cache เดิมเพื่อประสิทธิภาพ
        all_categories_hierarchical = get_cached_spare_part_categories_hierarchical()
        return jsonify({"success": True, "categories": all_categories_hierarchical})
    except Exception as e:
        current_app.logger.error(f"Error in api_get_spare_part_categories: {e}", exc_info=True)
        return jsonify({"success": False, "message": "เกิดข้อผิดพลาดในการดึงข้อมูลหมวดหมู่"}), 500

@bp.route('/tire_sales_history/<int:tire_id>')
@login_required
def tire_sales_history(tire_id):
    # Check permissions: You can choose who can view this data. 
    # For a sales history, `can_view_cost` might be a good fit, or simply `is_authenticated`.
    if not current_user.can_view_cost(): 
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้ารายงานการขาย', 'danger')
        return redirect(url_for('stock.index'))
    
    conn = get_db()
    
    # First, get the basic tire details to display on the page
    tire_info = database.get_tire(conn, tire_id)
    if not tire_info:
        flash('ไม่พบยางที่ระบุ', 'danger')
        conn.rollback()
        return redirect(url_for('stock.index', tab='tires'))

    # Then, get the sales history for this tire using the new function
    sales_history = database.get_tire_sales_history(conn, tire_id)

    return render_template('tire_sales_history.html', 
                           tire=tire_info, 
                           sales_history=sales_history, 
                           current_user=current_user)

@bp.route('/search_tires', methods=['GET', 'POST'])
@login_required
def search_tires():
    search_results = []
    search_query = None
    if request.method == 'POST':
        search_query = request.form.get('search_query')
        if search_query:
            conn = get_db()
            # The search_tires_by_keyword function you created in database.py
            search_results = database.search_tires_by_keyword(conn, search_query)
            # REMOVE THIS LINE: conn.close()
            # The teardown_appcontext will handle closing the connection at the end of the request.

    return render_template('search_tires.html', search_results=search_results, search_query=search_query)

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]    

@bp.route('/sales_history_search', methods=['GET'])
@login_required
def sales_history_search():
    if not current_user.can_view_cost():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้ารายงานการขาย', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()

    tire_id = request.args.get('tire_id', type=int)
    customer_keyword = request.args.get('customer_keyword')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    sales_history = []
    # เพิ่มตัวแปร has_searched เพื่อเช็คว่ามีการค้นหาหรือไม่
    has_searched = False

    has_search_params = any([tire_id, customer_keyword, start_date, end_date])

    if has_search_params:
        has_searched = True
        sales_history = database.search_sales_history(
            conn,
            tire_id=tire_id,
            customer_keyword=customer_keyword,
            start_date=start_date,
            end_date=end_date
        )

    tire_keyword_display = None
    if tire_id:
        tire_info = database.get_tire(conn, tire_id)
        if tire_info:
            tire_keyword_display = f"{tire_info['brand'].title()} {tire_info['model'].title()} ({tire_info['size']})"

    total_all_items = 0
    total_by_brand = defaultdict(int)

    for sale in sales_history:
        total_all_items += sale['quantity_change']
        total_by_brand[sale['tire_brand']] += sale['quantity_change']

    return render_template(
        'sales_history_search.html',
        sales_history=sales_history,
        tire_keyword=tire_keyword_display,
        customer_keyword=customer_keyword,
        start_date=start_date,
        end_date=end_date,
        THAI_MONTHS=THAI_MONTHS,
        total_all_items=total_all_items,
        total_by_brand=dict(total_by_brand),
        has_searched=has_searched # <-- ส่งตัวแปรใหม่
    )

@bp.route('/api/search_customers')
@login_required
def api_search_customers():
    # ตรวจสอบสิทธิ์การเข้าถึง หากไม่ต้องการให้ทุกคนเห็นรายชื่อลูกค้า
    # if not current_user.can_view_cost():
    #     return jsonify([])

    search_term = request.args.get('term', '').strip()
    if not search_term:
        return jsonify([])
    
    conn = get_db()
    
    # ใช้ฟังก์ชันใหม่ใน database.py เพื่อค้นหาลูกค้า
    customers = database.search_customers_by_keyword(conn, search_term)

    # จัดรูปแบบผลลัพธ์ให้เป็น array ของ string ตามที่ jQuery UI ต้องการ
    customer_names = [customer['name'] for customer in customers]

    return jsonify(customer_names)

@bp.route('/api/search_tires_for_autocomplete')
@login_required
def api_search_tires_for_autocomplete():
    search_term = request.args.get('term', '').strip()
    if not search_term:
        return jsonify([])
    
    conn = get_db()
    tires = database.search_tires_by_keyword(conn, search_term)

    # แก้ไขส่วนนี้: ส่งค่าเป็น Dictionary ที่มีทั้ง id และ value สำหรับ Autocomplete
    results = [
        {"id": t['id'], "label": f"{t['brand'].title()} {t['model'].title()} ({t['size']})", "value": f"{t['brand'].title()} {t['model'].title()} ({t['size']})"}
        for t in tires
    ]

    return jsonify(results)

@bp.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

@bp.route('/manage_label_presets', methods=['GET', 'POST'])
@login_required
def manage_label_presets():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add' or action == 'update':
                data = {
                    'name': request.form['name'],
                    'paper_width': float(request.form['paper_width']),
                    'paper_height': float(request.form['paper_height']),
                    'label_width': float(request.form['label_width']),
                    'label_height': float(request.form['label_height']),
                    'columns': int(request.form['columns']),
                    'row_gap': float(request.form.get('row_gap', 0)),
                    'column_gap': float(request.form.get('column_gap', 0)),
                    'margin_top': float(request.form.get('margin_top', 10)),
                    'margin_left': float(request.form.get('margin_left', 10))
                }
                if action == 'add':
                    database.add_label_preset(conn, data)
                    flash('เพิ่มโปรไฟล์การพิมพ์ใหม่สำเร็จ!', 'success')
                else:
                    preset_id = int(request.form['preset_id'])
                    database.update_label_preset(conn, preset_id, data)
                    flash('อัปเดตโปรไฟล์การพิมพ์สำเร็จ!', 'success')

            elif action == 'delete':
                preset_id = int(request.form['preset_id'])
                database.delete_label_preset(conn, preset_id)
                flash('ลบโปรไฟล์การพิมพ์สำเร็จ!', 'success')

            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาด: {e}', 'danger')

        return redirect(url_for('stock.manage_label_presets'))

    raw_presets = database.get_all_label_presets(conn)
    presets = [dict(row) for row in raw_presets]
    return render_template('manage_label_presets.html', presets=presets, current_user=current_user)

def calculate_ean13_check_digit(number_str):
    """คำนวณ Check Digit สำหรับ EAN-13"""
    if not number_str.isdigit() or len(number_str) != 12:
        raise ValueError("ต้องเป็นตัวเลข 12 หลักเท่านั้น")
    
    # ผลรวมเลขตำแหน่งคี่ (1, 3, 5, ...)
    odd_sum = sum(int(digit) for digit in number_str[0::2])
    # ผลรวมเลขตำแหน่งคู่ (2, 4, 6, ...)
    even_sum = sum(int(digit) for digit in number_str[1::2])
    
    total_sum = odd_sum + (even_sum * 3)
    
    # หาเลขที่บวกแล้วจะครบ 10 พอดี
    check_digit = (10 - (total_sum % 10)) % 10
    return str(check_digit)

@bp.route('/api/generate_unique_barcode/<item_type>') # Route ยังคงเดิม
@login_required
def api_generate_unique_barcode(item_type):
    try:
        timestamp_part = get_bkk_time().strftime('%y%m%d%H%M%S') # YYMMDDHHMMSS -> 12 หลัก
        unique_part = timestamp_part[3:] # เอา 9 ตัวหลัง
        base_12_digits = f"885{unique_part}"
        check_digit = calculate_ean13_check_digit(base_12_digits)
        new_barcode = f"{base_12_digits}{check_digit}"

        return jsonify({"success": True, "new_barcode": new_barcode})

    except Exception as e:
        current_app.logger.error(f"Error generating unique EAN-13 barcode: {e}", exc_info=True)
        return jsonify({"success": False, "message": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"}), 500

@bp.route('/change_password/<int:user_id>', methods=['POST'])
@login_required
def change_password(user_id):
    # ตรวจสอบสิทธิ์ Admin เท่านั้นที่เปลี่ยนรหัสผ่านคนอื่นได้
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการเปลี่ยนรหัสผ่าน', 'danger')
        return redirect(url_for('stock.manage_users'))

    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not new_password or not confirm_password:
        flash('กรุณากรอกรหัสผ่านใหม่และยืนยันรหัสผ่าน', 'danger')
        return redirect(url_for('stock.manage_users'))

    if new_password != confirm_password:
        flash('รหัสผ่านใหม่และการยืนยันไม่ตรงกัน', 'danger')
        return redirect(url_for('stock.manage_users'))

    conn = get_db()
    try:
        # เรียกใช้ฟังก์ชันใหม่จาก database.py
        database.change_user_password(conn, user_id, new_password)
        conn.commit()
        flash(f'เปลี่ยนรหัสผ่านสำหรับผู้ใช้ ID {user_id} สำเร็จ!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดในการเปลี่ยนรหัสผ่าน: {e}', 'danger')

    return redirect(url_for('stock.manage_users'))

@bp.route('/api/tires', methods=['GET'])
@api_key_required
def get_tires_for_botnoi():
    """
    API endpoint for Botnoi to query tire information.
    """
    tire_query = request.args.get('tire_query')
    
    if not tire_query:
        return jsonify({"error": "Missing tire_query parameter"}), 400
    
    try:
        conn = get_db()
        # เรียกใช้ฟังก์ชันที่เราสร้างใน database.py
        found_tires = database.find_tires(conn, tire_query)
        
        # จัดรูปแบบผลลัพธ์ให้อยู่ใน JSON ที่บอทสามารถอ่านได้ง่าย
        if found_tires:
            return jsonify({
                "status": "success",
                "message": f"Found {len(found_tires)} result(s) for '{tire_query}'",
                "results": found_tires
            })
        else:
            return jsonify({
                "status": "not_found",
                "message": f"No tires found for '{tire_query}'"
            })
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/product_analysis')
@login_required
def product_analysis():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    search_query = request.args.get('search_query', '').strip()
    brand_filter = request.args.get('brand_filter', 'all').strip()

    try:
        end_date_filter = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else get_bkk_time().date()
        start_date_filter = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else end_date_filter - timedelta(days=180)
    except ValueError:
        flash("รูปแบบวันที่ไม่ถูกต้อง", "danger")
        end_date_filter = get_bkk_time().date()
        start_date_filter = end_date_filter - timedelta(days=180)

    # สร้าง Dictionary เพื่อจัดกลุ่มตามยี่ห้อ
    action_items_by_brand = defaultdict(list)
    low_stock_items_by_brand = defaultdict(list)
    normal_stock_items_by_brand = defaultdict(list)
    total_visible_items = 0

    try:
        all_tire_recommendations = database.generate_stock_recommendations(
            conn, 
            start_date=start_date_filter, 
            end_date=end_date_filter,
            search_query=search_query,
            brand_filter=brand_filter
        )
        
        total_visible_items = len(all_tire_recommendations)

        for item in all_tire_recommendations:
            brand = item.get('brand', 'ไม่ระบุยี่ห้อ') # ดึงชื่อยี่ห้อ, ถ้าไม่มีให้ใช้ "ไม่ระบุยี่ห้อ"
            if item['urgency'] == 'critical':
                action_items_by_brand[brand].append(item)
            elif item['urgency'] == 'warning':
                low_stock_items_by_brand[brand].append(item)
            else:
                normal_stock_items_by_brand[brand].append(item)

    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการสร้างข้อมูลวิเคราะห์: {e}", "danger")
        # ในกรณีเกิด error ให้ dictionary ทั้งหมดเป็นค่าว่าง
        action_items_by_brand.clear()
        low_stock_items_by_brand.clear()
        normal_stock_items_by_brand.clear()
        
    available_tire_brands = database.get_all_tire_brands(conn)

    return render_template('product_analysis.html',
                           action_items_by_brand=action_items_by_brand,
                           low_stock_items_by_brand=low_stock_items_by_brand,
                           normal_stock_items_by_brand=normal_stock_items_by_brand,
                           start_date_filter=start_date_filter.strftime('%Y-%m-%d'),
                           end_date_filter=end_date_filter.strftime('%Y-%m-%d'),
                           search_query_filter=search_query,
                           brand_filter=brand_filter,
                           available_tire_brands=available_tire_brands,
                           total_visible_items=total_visible_items,
                           current_user=current_user)


@bp.route('/admin/fix_commissions', methods=['POST'])
@login_required
def fix_commissions_action():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์ในการดำเนินการนี้', 'danger')
        return redirect(url_for('stock.admin_dashboard'))
    
    conn = get_db()
    try:
        fixed_count = database.fix_historical_commission_data(conn)
        conn.commit()
        flash(f'ซ่อมแซมข้อมูลค่าคอมมิชชั่นในอดีตสำเร็จ! (แก้ไขทั้งหมด {fixed_count} รายการ)', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'เกิดข้อผิดพลาดระหว่างการซ่อมแซมข้อมูล: {e}', 'danger')
        
    return redirect(url_for('stock.admin_dashboard'))

@bp.route('/api/save_and_recalculate_lead_time', methods=['POST'])
@login_required
def api_save_and_recalculate_lead_time():
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    data = request.json
    item_id = data.get('item_id')
    item_type = data.get('item_type')
    brand = data.get('brand')

    # --- START: โค้ดที่แก้ไข ---
    lead_time_value = data.get('lead_time', 7) # 1. Get the value, default is 7
    try:
        lead_time_days = int(lead_time_value) # 2. Try to convert to integer
    except (ValueError, TypeError):
        lead_time_days = 7 # Fallback to 7 if conversion fails
    # --- END: โค้ดที่แก้ไข ---

    if not all([item_id, item_type, brand]):
        return jsonify({"success": False, "message": "ข้อมูลไม่ครบถ้วน"}), 400

    conn = get_db()
    try:
        database.save_brand_lead_time(conn, brand, lead_time_days)
        conn.commit()

        result = database.calculate_single_item_recommendation(conn, item_id, item_type, lead_time_days)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@bp.route('/api/toggle_analysis_status', methods=['POST'])
@login_required
def api_toggle_analysis_status():
    """
    API Endpoint สำหรับปุ่ม "ซ่อน" (Ignore)
    """
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    data = request.json
    item_id = data.get('item_id')
    item_type = data.get('item_type')
    ignore_status = data.get('ignore', True)

    if not all([item_id, item_type]):
        return jsonify({"success": False, "message": "ข้อมูลไม่ครบถ้วน"}), 400

    conn = get_db()
    try:
        database.toggle_item_analysis_status(conn, item_type, item_id, ignore_status)
        conn.commit()
        return jsonify({"success": True, "message": "อัปเดตสถานะสำเร็จ"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@bp.route('/admin/manage_ignored_items', methods=['GET', 'POST'])
@login_required
def manage_ignored_items():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('stock.index'))

    conn = get_db()
    if request.method == 'POST':
        item_type = request.form.get('item_type')
        item_id = request.form.get('item_id', type=int)
        
        if item_type and item_id:
            try:
                database.restore_item_to_analysis(conn, item_type, item_id)
                conn.commit()
                flash('นำรายการกลับสู่การวิเคราะห์สำเร็จ!', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'เกิดข้อผิดพลาด: {e}', 'danger')
        return redirect(url_for('stock.manage_ignored_items'))

    # สำหรับ GET request
    ignored_items = database.get_all_ignored_items(conn)
    return render_template('manage_ignored_items.html', 
                           ignored_items=ignored_items, 
                           current_user=current_user)

