import os
import json
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib.colors import black, grey, lightgrey, whitesmoke
from io import BytesIO
from collections import defaultdict

# --- ส่วนของการตั้งค่าฟอนต์ ---
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

THAI_FONT_LOADED = False
try:
    pdfmetrics.registerFont(TTFont('Sarabun', 'THSarabunNew.ttf'))
    pdfmetrics.registerFont(TTFont('Sarabun-Bold', 'THSarabunNew Bold.ttf'))
    THAI_FONT_LOADED = True
except Exception as e:
    print(f"Warning: Thai fonts not found. Falling back to Helvetica. Error: {e}")

styles = getSampleStyleSheet()
normal_font = 'Sarabun' if THAI_FONT_LOADED else 'Helvetica'
bold_font = 'Sarabun-Bold' if THAI_FONT_LOADED else 'Helvetica-Bold'

styles.add(ParagraphStyle(name='TitleStyle', fontName=bold_font, fontSize=20, alignment=TA_CENTER, spaceAfter=14))
styles['Normal'].fontName = normal_font
styles['Normal'].fontSize = 12
styles.add(ParagraphStyle(name='SmallText', fontName=normal_font, fontSize=10, leading=12))
styles.add(ParagraphStyle(name='NormalRight', fontName=normal_font, fontSize=12, alignment=TA_RIGHT))
styles.add(ParagraphStyle(name='NormalCenter', fontName=normal_font, fontSize=12, alignment=TA_CENTER))
styles.add(ParagraphStyle(name='BoldSmallText', fontName=bold_font, fontSize=10))
# --- สิ้นสุดส่วนตั้งค่าฟอนต์ ---


### Helper Function: สร้างตารางรายการสินค้า (ใช้ร่วมกัน) ###
def _build_items_table(options, job_items_list):
    table_columns_options = options.get('table_columns', [])
    visible_columns = [col for col in table_columns_options if col.get('show')]
    
    if not visible_columns:
        return Spacer(0, 0)

    table_headers = [Paragraph('<b>#</b>', styles['NormalCenter'])]
    col_widths = [1.5*cm]
    available_width = 16.5*cm

    num_visible = len(visible_columns)
    desc_width_ratio = 0.45
    non_desc_width = available_width * (1 - desc_width_ratio)
    other_col_width = non_desc_width / (num_visible - 1 if num_visible > 1 else 1)
    
    for col in visible_columns:
        table_headers.append(Paragraph(f"<b>{col.get('label', '')}</b>", styles['NormalCenter']))
        if col.get('key') == 'description': col_widths.append(available_width * desc_width_ratio)
        else: col_widths.append(other_col_width)

    table_data = [table_headers]
    for i, item in enumerate(job_items_list):
        row_data = [str(i+1)]
        for col in visible_columns:
            key = col.get('key')
            original_price = item.get('original_unit_price', item.get('unit_price', 0)) or 0
            final_price = item.get('unit_price', 0) or 0
            quantity = item.get('quantity', 0) or 0
            total_discount = (original_price - final_price) * quantity

            if key == 'description':
                row_data.append(Paragraph(item.get('description', ''), styles['SmallText']))
            elif key == 'quantity':
                row_data.append(Paragraph(str(quantity), styles['NormalCenter']))
            elif key == 'unit_price':
                row_data.append(Paragraph(f"{original_price:,.2f}", styles['NormalRight']))
            elif key == 'discount':
                row_data.append(Paragraph(f"{total_discount:,.2f}" if total_discount > 0 else '-', styles['NormalRight']))
            elif key == 'total_price':
                row_data.append(Paragraph(f"{item.get('total_price', 0):,.2f}", styles['NormalRight']))
        table_data.append(row_data)

    items_table = Table(table_data, colWidths=col_widths)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), whitesmoke),
        ('GRID', (0,0), (-1,-1), 1, grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,0), (-1,-1), normal_font),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('ALIGN', (1,1), (1,-1), 'LEFT'),
    ]))
    return items_table


### ฟังก์ชันสำหรับ "ใบรับรถ" (Layout มาตรฐาน) ###
def generate_job_order_pdf(job_data, template_data):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
        Story = []
        
        options = template_data.get('options', {})

        shop_info = f"<b>{template_data.get('shop_name') or 'ชื่อร้านของคุณ'}</b><br/><font size='9'>{template_data.get('shop_details') or 'ที่อยู่และเบอร์โทรศัพท์'}</font>"
        header_title = template_data.get('header_text') or 'ใบรับรถ / ใบแจ้งซ่อม'

        header_data = [[Paragraph(shop_info, styles['NormalCenter']), Paragraph(f"<b>{header_title}</b><br/>Job Order", styles['TitleStyle'])]]
        header_table = Table(header_data, colWidths=[9*cm, 9*cm], style=[('VALIGN', (0,0), (-1,-1), 'TOP'), ('ALIGN', (1,0), (1,0), 'RIGHT')])
        Story.append(header_table)

        customer_info = f"<b>ลูกค้า:</b> {job_data.get('customer_name') or '-'}<br/><b>เบอร์โทร:</b> {job_data.get('customer_phone') or '-'}<br/><b>ทะเบียนรถ:</b> {job_data.get('car_plate') or '-'}<br/><b>รุ่นรถ:</b> {job_data.get('car_brand') or '-'}"
        doc_info = f"<b>เลขที่เอกสาร:</b> {job_data['job_number']}<br/><b>วันที่:</b> {job_data['created_at'].strftime('%d/%m/%Y %H:%M')}<br/><b>พนักงาน:</b> {job_data.get('created_by_username') or '-'}<br/><b>ช่างผู้รับผิดชอบ:</b> {job_data.get('technician_name') or 'ยังไม่ระบุ'}"
        info_table = Table([[Paragraph(customer_info, styles['SmallText']), Paragraph(doc_info, styles['SmallText'])]], colWidths=[9*cm, 9*cm], spaceBefore=10)
        info_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, grey), ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 10), ('BOTTOMPADDING', (0,0), (-1,-1), 10), ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        Story.append(info_table)
        Story.append(Spacer(1, 0.5*cm))
        Story.append(Paragraph("<b><u>รายการบริการ / สินค้า</u></b>", styles['Normal']))
        Story.append(Spacer(1, 0.2*cm))
        
        items_table = _build_items_table(options, job_data['job_items_list'])
        Story.append(items_table)

        notes_and_terms_data = [
            [Paragraph(f"<b>หมายเหตุ / อาการที่ลูกค้าแจ้ง:</b><br/>{job_data.get('notes') or 'ไม่มี'}", styles['SmallText'])],
            [Paragraph("<b>ข้อตกลงและเงื่อนไข:</b><br/><font size='8'>1. ทางร้านจะไม่รับผิดชอบทรัพย์สินมีค่าที่ไม่ได้นำฝากไว้กับพนักงาน<br/>2. กรุณาตรวจสอบสภาพรถยนต์และรายการซ่อมก่อนออกจากร้าน</font>", styles['SmallText'])]
        ]
        notes_and_terms_table = Table(notes_and_terms_data, colWidths=[18*cm], spaceBefore=10, style=[
            ('BOX', (0,0), (-1,-1), 1, grey), ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 10), ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ])
        Story.append(notes_and_terms_table)
        Story.append(Spacer(1, 1*cm))

        footer_sig_1 = template_data.get('footer_signature_1') or '(ลูกค้า)'
        footer_sig_2 = template_data.get('footer_signature_2') or '(พนักงานรับรถ)'
        footer_data = [
            [Paragraph("", styles['NormalCenter']), Paragraph("", styles['NormalCenter'])],
            [Paragraph('.......................................', styles['NormalCenter']), Paragraph('.......................................', styles['NormalCenter'])],
            [Paragraph(footer_sig_1, styles['NormalCenter']), Paragraph(footer_sig_2 , styles['NormalCenter'])]
        ]
        footer_table = Table(footer_data, colWidths=[9*cm, 9*cm], rowHeights=[1*cm, 0.5*cm, 0.5*cm])
        Story.append(footer_table)

        doc.build(Story)
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"!!! PDF Generation FAILED for Job Order {job_data.get('job_number')} !!!")
        print(e)
        return None


### ฟังก์ชันสำหรับ "ใบเสร็จรับเงิน" ###
def generate_receipt_pdf(job_data, template_data):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
        Story = []
        
        options = template_data.get('options', {})

        shop_info = f"<b>{template_data.get('shop_name') or 'ชื่อร้านของคุณ'}</b><br/><font size='9'>{template_data.get('shop_details') or 'ที่อยู่และเบอร์โทรศัพท์'}</font>"
        header_title = template_data.get('header_text') or 'ใบเสร็จรับเงิน'
        
        header_data = [[Paragraph(shop_info, styles['NormalCenter']), Paragraph(f"<b>{header_title}</b><br/>Receipt", styles['TitleStyle'])]]
        header_table = Table(header_data, colWidths=[9*cm, 9*cm], style=[('VALIGN', (0,0), (-1,-1), 'TOP'), ('ALIGN', (1,0), (1,0), 'RIGHT')])
        Story.append(header_table)

        completed_date_str = job_data['completed_at'].strftime('%d/%m/%Y') if job_data.get('completed_at') else 'N/A'
        
        customer_info = f"<b>ลูกค้า:</b> {job_data.get('customer_name') or '-'}<br/><b>เบอร์โทร:</b> {job_data.get('customer_phone') or '-'}<br/><b>ทะเบียนรถ:</b> {job_data.get('car_plate') or '-'}<br/><b>รุ่นรถ:</b> {job_data.get('car_brand') or '-'}"
        doc_info = f"<b>เลขที่เอกสาร:</b> {job_data['job_number']}<br/><b>วันที่ชำระเงิน:</b> {completed_date_str}<br/><b>ผู้รับเงิน:</b> {job_data.get('created_by_username') or '-'}"
        info_table = Table([[Paragraph(customer_info, styles['SmallText']), Paragraph(doc_info, styles['SmallText'])]], colWidths=[9*cm, 9*cm], spaceBefore=10)
        info_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, grey), ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 10), ('BOTTOMPADDING', (0,0), (-1,-1), 10), ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        Story.append(info_table)
        Story.append(Spacer(1, 0.5*cm))

        Story.append(Paragraph("<b><u>รายการ</u></b>", styles['Normal']))
        Story.append(Spacer(1, 0.2*cm))

        items_table = _build_items_table(options, job_data['job_items_list'])
        Story.append(items_table)
        Story.append(Spacer(1, 0.2*cm))

        summary_data = [['', Paragraph('<b>ยอดรวมก่อนภาษี</b>', styles['NormalRight']), f"{job_data['sub_total']:,.2f}"]]
        if job_data['vat'] > 0:
            summary_data.append(['', Paragraph('<b>ภาษีมูลค่าเพิ่ม (7%)</b>', styles['NormalRight']), f"{job_data['vat']:,.2f}"])
        summary_data.append(['', Paragraph('<b>ยอดชำระทั้งสิ้น</b>', styles['BoldSmallText']), Paragraph(f"<b>{job_data['grand_total']:,.2f}</b>", styles['NormalRight'])])
        
        available_page_width = A4[0] - 3*cm
        summary_label_width = 3.5*cm
        summary_value_width = 3.5*cm
        summary_spacer_width = available_page_width - summary_label_width - summary_value_width
        
        summary_table = Table(summary_data, colWidths=[summary_spacer_width, summary_label_width, summary_value_width])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('FONTNAME', (0,0), (-1,-1), normal_font),
            ('GRID', (1,-1), (-1,-1), 1, black), ('BACKGROUND', (1,-1), (-1,-1), lightgrey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        Story.append(summary_table)
        Story.append(Spacer(1, 1*cm))

        footer_sig_1 = template_data.get('footer_signature_1') or '(ลูกค้า)'
        footer_sig_2 = template_data.get('footer_signature_2') or '(ผู้รับเงิน)'
        footer_data = [
            [Paragraph("", styles['NormalCenter']), Paragraph("", styles['NormalCenter'])],
            [Paragraph('.......................................', styles['NormalCenter']), Paragraph('.......................................', styles['NormalCenter'])],
            [Paragraph(footer_sig_1, styles['NormalCenter']), Paragraph(footer_sig_2 , styles['NormalCenter'])]
        ]
        footer_table = Table(footer_data, colWidths=[9*cm, 9*cm], rowHeights=[1*cm, 0.5*cm, 0.5*cm])
        Story.append(footer_table)

        doc.build(Story)
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"!!! PDF Generation FAILED for Receipt {job_data.get('job_number')} !!!")
        print(e)
        return None