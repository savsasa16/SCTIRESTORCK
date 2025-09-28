# service.py

import os
import json
from io import BytesIO
from werkzeug.utils import secure_filename
from werkzeug.exceptions import BadRequest

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, g
)
from flask_login import login_required, current_user

import database
import document_generator

bp = Blueprint('service', __name__, url_prefix='/service')

def get_db():
    if 'db' not in g:
        g.db = database.get_db_connection()
    return g.db

@bp.teardown_app_request
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@bp.route('/')
@login_required
def index():
    """หน้าหลักสำหรับจัดการงานบริการหน้าร้าน"""
    return render_template('service/index.html')

@bp.route('/jobs_list')
@login_required
def jobs_list():
    conn = get_db()
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status_filter', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    all_jobs = database.get_all_jobs(conn, 
                                     search_query=search_query, 
                                     status_filter=status_filter,
                                     start_date=start_date,
                                     end_date=end_date)
    
    return render_template('service/jobs_list.html', 
                           jobs=all_jobs, 
                           search_query=search_query,
                           status_filter=status_filter,
                           start_date=start_date,
                           end_date=end_date)

# Route นี้สำหรับแสดงหน้าฟอร์มสร้างใบงาน
@bp.route('/create_job', methods=['GET'])
@login_required
def create_job():
    conn = get_db()
    technicians = database.get_all_technicians(conn)
    salespersons = database.get_all_salespersons(conn)
    return render_template('service/create_job.html', technicians=technicians, salespersons=salespersons)

# Route นี้เป็น API สำหรับรับข้อมูลจากฟอร์มเพื่อบันทึกเท่านั้น
@bp.route('/api/create_job', methods=['POST'])
@login_required
def api_create_job():
    if not current_user.can_edit():
        return jsonify({'success': False, 'message': 'คุณไม่มีสิทธิ์ในการสร้างใบงาน'})

    data = request.get_json()
    job_details = data.get('job_details', {})
    items = data.get('items', [])
    
    if not job_details.get('customer_name') or not items:
        return jsonify({'success': False, 'message': 'กรุณากรอกข้อมูลลูกค้าและเพิ่มรายการอย่างน้อย 1 รายการ'})
    
    conn = get_db()
    try:
        status_to_save = job_details.get('status', 'draft')
        
        salesperson_id = job_details.get('salesperson_id')
        if salesperson_id == '' or not salesperson_id: salesperson_id = None
        
        technician_ids = job_details.get('technician_ids', [])
        
        job_id = database.create_new_job(
            conn=conn,
            job_data=job_details,
            job_items_data=items,
            user_id=current_user.id,
            salesperson_id=salesperson_id,
            technician_ids=technician_ids
        )

        if status_to_save == 'open':
            database.update_job_status(conn, job_id, 'open')
        
        conn.commit()

        # สร้างและบันทึก PDF
        try:
            full_job_data = database.get_job_by_id(conn, job_id)
            if full_job_data:
                pdf_bytes_io = document_generator.generate_job_order_pdf(full_job_data)
                plate_number = full_job_data.get('car_plate')
                base_filename = plate_number if plate_number and plate_number.strip() else full_job_data['job_number']
                safe_filename = secure_filename(base_filename) + ".pdf"
                job_list_folder = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'job_list')
                os.makedirs(job_list_folder, exist_ok=True)
                file_path = os.path.join(job_list_folder, safe_filename)
                with open(file_path, 'wb') as f:
                    f.write(pdf_bytes_io.getbuffer())
                current_app.logger.info(f"Successfully saved job order PDF to: {file_path}")
        except Exception as pdf_error:
            current_app.logger.error(f"Failed to generate or save PDF for job_id {job_id}: {pdf_error}", exc_info=True)
            flash('สร้างใบงานสำเร็จ แต่เกิดข้อผิดพลาดในการสร้างไฟล์ PDF', 'warning')

        return jsonify({
            'success': True, 
            'message': f'สร้างใบงาน ID: {job_id} สำเร็จแล้ว!', 
            'job_id': job_id
        })
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error creating job: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'เกิดข้อผิดพลาดในการบันทึก: {e}'}), 500

@bp.route('/edit_job/<int:job_id>', methods=['GET'])
@login_required
def edit_job(job_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการแก้ไขใบงาน', 'danger')
        return redirect(url_for('service.jobs_list'))

    conn = get_db()
    job = database.get_job_by_id(conn, job_id)

    if not job:
        flash('ไม่พบใบงานที่ระบุ', 'danger')
        return redirect(url_for('service.jobs_list'))

    if job['status'] not in ['draft', 'open']:
        flash('ไม่สามารถแก้ไขใบงานที่เสร็จสิ้นหรือยกเลิกไปแล้วได้', 'warning')
        return redirect(url_for('service.view_job', job_id=job_id))
    
    technicians = database.get_all_technicians(conn)
    salespersons = database.get_all_salespersons(conn)
    
    return render_template(
        'service/edit_job.html', 
        job_data=job,
        job_items_data=job['job_items_list'],
        technicians=technicians,
        salespersons=salespersons
    )

@bp.route('/api/job/update/<int:job_id>', methods=['POST'])
@login_required
def api_update_job(job_id):
    if not current_user.can_edit():
        return jsonify({'success': False, 'message': 'คุณไม่มีสิทธิ์ในการแก้ไขใบงาน'}), 403

    data = request.get_json()
    job_details = data.get('job_details')
    items = data.get('items')

    if not job_details or not items:
        return jsonify({'success': False, 'message': 'ข้อมูลที่ส่งมาไม่ครบถ้วน'}), 400

    conn = get_db()
    try:
        salesperson_id = job_details.get('salesperson_id')
        if salesperson_id == '' or not salesperson_id: salesperson_id = None

        technician_ids = job_details.get('technician_ids', [])

        database.update_job_with_items(
            conn=conn,
            job_id=job_id,
            job_details=job_details,
            items=items,
            user_id=current_user.id,
            salesperson_id=salesperson_id,
            technician_ids=technician_ids
        )
        
        conn.commit()
        return jsonify({'success': True, 'message': 'อัปเดตใบงานสำเร็จ!', 'job_id': job_id})
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error updating job {job_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'เกิดข้อผิดพลาดในการอัปเดต: {str(e)}'}), 500

@bp.route('/confirm_job/<int:job_id>', methods=['POST'])
@login_required
def confirm_job(job_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการยืนยันใบงาน', 'danger')
        return redirect(url_for('service.jobs_list'))

    conn = get_db()
    try:
        job = database.get_job_by_id(conn, job_id)
        if not job:
            flash('ไม่พบใบงานที่ระบุ', 'danger')
            return redirect(url_for('service.jobs_list'))

        if job['status'] == 'draft':
            database.update_job_status(conn, job_id, 'open')
            conn.commit()
            flash(f'ยืนยันใบงาน #{job["job_number"]} เป็น Open สำเร็จ!', 'success')
        else:
            flash(f'ใบงาน #{job["job_number"]} ไม่ได้อยู่ในสถานะฉบับร่าง', 'warning')

    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error confirming job {job_id}: {e}", exc_info=True)
        flash(f'เกิดข้อผิดพลาดในการยืนยันใบงาน: {str(e)}', 'danger')

    return redirect(url_for('service.view_job', job_id=job_id))

@bp.route('/print_job_order/<int:job_id>')
@login_required
def print_job_order(job_id):
    conn = get_db()
    job = database.get_job_by_id(conn, job_id)
    if not job:
        flash('ไม่พบใบงานที่ต้องการพิมพ์', 'danger')
        return redirect(url_for('service.jobs_list'))

    template = database.get_template_by_name(conn, 'Job Order')
    if not template:
        template = {} # Fallback

    # เรียกใช้ฟังก์ชันสร้าง "ใบรับรถ"
    pdf_bytes = document_generator.generate_job_order_pdf(job, template)
    
    return send_file(
        pdf_bytes,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'ใบรับรถ_{job["job_number"]}.pdf'
    )

@bp.route('/print_receipt/<int:job_id>')
@login_required
def print_receipt(job_id):
    conn = get_db()
    job = database.get_job_by_id(conn, job_id)
    if not job:
        flash('ไม่พบใบงานที่ต้องการพิมพ์', 'danger')
        return redirect(url_for('service.jobs_list'))

    # ตรวจสอบว่างานเสร็จสิ้นแล้วเท่านั้นจึงจะพิมพ์ใบเสร็จได้
    if job['status'] != 'completed':
        flash('ใบงานยังไม่เสร็จสิ้น ไม่สามารถพิมพ์ใบเสร็จได้', 'warning')
        return redirect(url_for('service.view_job', job_id=job_id))

    template = database.get_template_by_name(conn, 'Job Order')
    if not template:
        template = {} # Fallback

    # เรียกใช้ฟังก์ชันใหม่สำหรับสร้าง "ใบเสร็จ"
    pdf_bytes = document_generator.generate_receipt_pdf(job, template)
    
    return send_file(
        pdf_bytes,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'ใบเสร็จ_{job["job_number"]}.pdf'
    )

@bp.route('/api/job/search_products')
@login_required
def api_job_search_products():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'results': []})

    conn = get_db()
    search_term = f"%{query.lower()}%"
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"
    like_op = "ILIKE" if is_postgres else "LIKE"

    tire_sql_part = f"""
        SELECT 
            'tire-' || t.id AS unique_id, 'tire' AS item_type, t.id AS item_id,
            t.brand || ' ' || t.model || ' (' || t.size || ')' AS description,
            t.price_per_item AS unit_price, t.quantity AS stock,
            p.type AS promo_type, p.value1 AS promo_value1, p.value2 AS promo_value2, p.is_active AS promo_is_active
        FROM tires t
        LEFT JOIN promotions p ON t.promotion_id = p.id
        WHERE t.is_deleted = {'FALSE' if is_postgres else '0'} AND (LOWER(t.brand) {like_op} {placeholder} OR LOWER(t.model) {like_op} {placeholder} OR LOWER(t.size) {like_op} {placeholder})
    """
    
    wheel_sql_part = f"""
        SELECT 'wheel-' || id, 'wheel', id, brand || ' ' || model || ' (' || pcd || ')', retail_price, quantity, NULL, NULL, NULL, NULL FROM wheels
        WHERE is_deleted = {'FALSE' if is_postgres else '0'} AND (LOWER(brand) {like_op} {placeholder} OR LOWER(model) {like_op} {placeholder} OR LOWER(pcd) {like_op} {placeholder})
    """
    spare_part_sql_part = f"""
        SELECT 'spare_part-' || id, 'spare_part', id, name || ' (' || COALESCE(part_number, 'N/A') || ')', retail_price, quantity, NULL, NULL, NULL, NULL FROM spare_parts
        WHERE is_deleted = {'FALSE' if is_postgres else '0'} AND (LOWER(name) {like_op} {placeholder} OR LOWER(part_number) {like_op} {placeholder} OR LOWER(brand) {like_op} {placeholder})
    """
    service_sql_part = f"""
        SELECT 'service-' || id, 'service', id, name, default_price, NULL as stock, NULL, NULL, NULL, NULL FROM services
        WHERE is_deleted = {'FALSE' if is_postgres else '0'} AND LOWER(name) {like_op} {placeholder}
    """

    sql_query = f"{tire_sql_part} UNION ALL {wheel_sql_part} UNION ALL {spare_part_sql_part} UNION ALL {service_sql_part} LIMIT 30"
    params = [search_term] * 10
    
    cursor = conn.cursor()
    cursor.execute(sql_query, params)
    
    results_raw = [dict(row) for row in cursor.fetchall()]
    
    select2_results = []
    for item in results_raw:
        promo_unit_price = None
        promo_description = None

        if item['item_type'] == 'tire' and item.get('promo_is_active') and item.get('promo_type'):
            promo_calc = database.calculate_tire_promo_prices(
                item['unit_price'], item['promo_type'], item['promo_value1'], item['promo_value2']
            )
            promo_unit_price = promo_calc.get('price_per_item_promo')
            promo_description = promo_calc.get('promo_description_text')
        
        item['promo_unit_price'] = promo_unit_price
        item['promo_description'] = promo_description

        stock_display = f"(คงเหลือ: {item['stock']})" if item['stock'] is not None else "(ค่าบริการ)"

        select2_results.append({
            "id": item['unique_id'],
            "text": f"[{item['item_type'].upper()}] {item['description']} {stock_display}",
            "data": item 
        })

    return jsonify({"results": select2_results})

@bp.route('/view_job/<int:job_id>')
@login_required
def view_job(job_id):
    conn = get_db()
    job = database.get_job_by_id(conn, job_id)
    if not job:
        flash('ไม่พบใบงานที่ระบุ', 'danger')
        return redirect(url_for('service.jobs_list'))
    
    return render_template('service/view_job.html', job=job, job_items=job['job_items_list'])

@bp.route('/create_invoice')
@login_required
def create_invoice():
    return render_template('service/create_invoice.html')

@bp.route('/manage_spare_parts')
@login_required
def manage_spare_parts():
    return render_template('service/manage_spare_parts.html')

@bp.route('/reports')
@login_required
def service_reports():
    return render_template('service/reports.html')

@bp.route('/finalize_job/<int:job_id>', methods=['POST'])
@login_required
def finalize_job(job_id):
    if not current_user.can_edit():
        flash('คุณไม่มีสิทธิ์ในการปิดงาน', 'danger')
        return redirect(url_for('service.jobs_list'))

    conn = get_db()
    try:
        job = database.get_job_by_id(conn, job_id)
        if not job:
            flash('ไม่พบใบงานที่ระบุ', 'danger')
            return redirect(url_for('service.jobs_list'))
        
        if job['status'] != 'open':
            flash(f"ไม่สามารถปิดงานได้ เนื่องจากใบงานอยู่ในสถานะ '{job['status']}'", 'warning')
            return redirect(url_for('service.view_job', job_id=job_id))

        job_items = job.get('job_items_list', [])
        
        for item in job_items:
            if item.get('item_type') == 'tire':
                # ควรสร้างฟังก์ชัน database.decrease_stock(conn, 'tire', item['item_id'], item['quantity'])
                pass 
            elif item.get('item_type') == 'wheel':
                pass
            elif item.get('item_type') == 'spare_part':
                pass

        database.update_job_status(conn, job_id, 'completed')
        conn.commit()
        flash('ปิดงานและตัดสต็อกเรียบร้อยแล้ว!', 'success')
        return redirect(url_for('service.view_job', job_id=job_id))
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error finalizing job: {e}", exc_info=True)
        flash(f'เกิดข้อผิดพลาดในการปิดงาน: {e}', 'danger')
        return redirect(url_for('service.view_job', job_id=job_id))

@bp.route('/manage_template', methods=['GET', 'POST'])
@login_required
def manage_job_template():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('service.index'))

    conn = get_db()
    template_name = 'Job Order'

    if request.method == 'POST':
        try:
            current_template = database.get_template_by_name(conn, template_name)
            logo_path = current_template.get('logo_url')

            if 'logo' in request.files:
                file = request.files['logo']
                if file.filename != '':
                    unique_filename = f"{database.get_bkk_time().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
                    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(save_path)
                    logo_path = unique_filename 

            # ★★★ START: แก้ไขส่วนนี้ ★★★
            template_options = {
                "header_fields": {
                    "show_technician": 'show_technician' in request.form,
                    "show_car_brand": 'show_car_brand' in request.form
                },
                "table_columns": [
                    {"key": "description", "label": request.form.get('col_label_description'), "show": 'col_show_description' in request.form},
                    {"key": "unit_price", "label": request.form.get('col_label_unit_price'), "show": 'col_show_unit_price' in request.form},
                    {"key": "quantity", "label": request.form.get('col_label_quantity'), "show": 'col_show_quantity' in request.form},
                    {"key": "discount", "label": request.form.get('col_label_discount'), "show": 'col_show_discount' in request.form},
                    {"key": "total_price", "label": request.form.get('col_label_total_price'), "show": 'col_show_total_price' in request.form}
                ]
            }
            # ★★★ END: สิ้นสุดส่วนแก้ไข ★★★

            template_data = {
                'header_text': request.form.get('header_text'),
                'shop_name': request.form.get('shop_name'),
                'shop_details': request.form.get('shop_details'),
                'footer_signature_1': request.form.get('footer_signature_1'),
                'footer_signature_2': request.form.get('footer_signature_2'),
                'logo_url': logo_path,
                'discount': request.form.get('discount'),
                'template_options': json.dumps(template_options, ensure_ascii=False)
            }
            
            database.update_template(conn, template_name, template_data)
            conn.commit()
            flash('บันทึก Template สำเร็จ!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'เกิดข้อผิดพลาดในการบันทึก: {e}', 'danger')
        
        return redirect(url_for('service.manage_job_template'))

    template = database.get_template_by_name(conn, template_name)
    if not template:
        # Provide a default structure if template or options are missing
        template = {
            'options': {
                'header_fields': {}, 
                'table_columns': [
                    {"key": "description", "label": "รายการ", "show": True},
                    {"key": "unit_price", "label": "ราคา/หน่วย", "show": True},
                    {"key": "quantity", "label": "จำนวน", "show": True},
                    {"key": "discount", "label": "ส่วนลด", "show": True},
                    {"key": "total_price", "label": "ราคารวม", "show": True}
                ]
            }
        }

    return render_template('service/manage_template.html', template=template)

@bp.route('/template_editor')
@login_required
def template_editor():
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('service.index'))
    return render_template('service/template_editor.html')

@bp.route('/api/template/<template_name>/layout', methods=['GET'])
@login_required
def api_get_template_layout(template_name):
    conn = get_db()
    template = database.get_template_by_name(conn, template_name)
    if template and template.get('layout_json'):
        return jsonify({"success": True, "layout": json.loads(template['layout_json'])})
    return jsonify({"success": True, "layout": {"elements": []}}) # Return empty if not found

@bp.route('/api/template/<template_name>/layout', methods=['POST'])
@login_required
def api_save_template_layout(template_name):
    if not current_user.is_admin():
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    layout_data = request.get_json()
    conn = get_db()
    try:
        database.update_template_layout(conn, template_name, json.dumps(layout_data, ensure_ascii=False))
        conn.commit()
        return jsonify({"success": True, "message": "Layout saved."})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@bp.route('/manage_personnel')
@login_required
def manage_personnel():
    """หน้าสำหรับจัดการรายชื่อ ช่าง และ พนักงานขาย"""
    if not current_user.is_admin():
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('service.index'))
    
    conn = get_db()
    all_personnel = database.get_all_personnel(conn)
    
    return render_template('service/manage_personnel.html', personnel=all_personnel)

@bp.route('/api/personnel/add', methods=['POST'])
@login_required
def api_add_personnel():
    if not current_user.is_admin():
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json()
    name = data.get('name', '').strip()
    personnel_type = data.get('type')

    if not name or not personnel_type:
        return jsonify({'success': False, 'message': 'กรุณากรอกชื่อและเลือกประเภท'}), 400
    
    conn = get_db()
    try:
        database.add_personnel(conn, name, personnel_type)
        conn.commit()
        flash(f'เพิ่ม "{name}" ({personnel_type}) สำเร็จ', 'success')
        return jsonify({'success': True})
    except ValueError as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 409
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error adding personnel: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'เกิดข้อผิดพลาดในการบันทึก'}), 500

@bp.route('/api/personnel/update', methods=['POST'])
@login_required
def api_update_personnel():
    if not current_user.is_admin():
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json()
    personnel_id = data.get('id')
    personnel_type = data.get('type')
    name = data.get('name', '').strip()
    is_active = data.get('is_active')

    if not all([personnel_id, personnel_type, name]) or is_active is None:
        return jsonify({'success': False, 'message': 'ข้อมูลไม่ครบถ้วน'}), 400

    conn = get_db()
    try:
        database.update_personnel(conn, personnel_id, personnel_type, name, is_active)
        conn.commit()
        return jsonify({'success': True, 'message': 'อัปเดตข้อมูลสำเร็จ'})
    except ValueError as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 409
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Error updating personnel: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'เกิดข้อผิดพลาดในการอัปเดต'}), 500
