from flask import Blueprint, request, jsonify, current_app
import requests
import re
from app import api_key_required
import database
import json

bp = Blueprint('webhook', __name__, url_prefix='/webhook')

# --- ส่วนนี้ไม่ต้องแก้ไข ---
TIRE_API_URL = "http://scstock.duckdns.org/api/tires"
API_KEY = database.os.getenv("API_SECRET_KEY")

def normalize_string(s):
    """Clean and normalize a string by removing all whitespace and converting to lowercase."""
    if not isinstance(s, str):
        return ""
    return ''.join(s.split()).lower()

def check_stock_and_profit(tire, quantity_to_check):
    try:
        qty_balance = int(tire.get('qty_balance', 0))
        if qty_balance < quantity_to_check:
            return False, None

        price_per_item = float(tire['price_per_item'])
        cost_sc = float(tire['cost_sc']) if tire.get('cost_sc') is not None else 0.0
        tire_size_str = tire.get('size', '')

        rim_size_match = re.search(r'R(\d{2})', tire_size_str)
        rim_size = int(rim_size_match.group(1)) if rim_size_match else 0

        if 16 <= rim_size <= 20:
            shipping_cost_per_tire = 130
        elif rim_size == 15:
            shipping_cost_per_tire = 100
        else:
            shipping_cost_per_tire = 0

        base_price = (price_per_item * 4) - 600
        if quantity_to_check == 1:
            unit_sale_price = (base_price / 4) + 50
        elif quantity_to_check == 2:
            unit_sale_price = ((base_price / 2) + 100) / 2
        elif quantity_to_check == 4:
            unit_sale_price = base_price / 4
        else:
            unit_sale_price = (base_price / 4) + 50  # default กรณีอื่น

        total_sale_price = unit_sale_price * quantity_to_check
        cod_service_charge = total_sale_price * 0.01
        total_cost = (cost_sc + shipping_cost_per_tire) * quantity_to_check

        profit = total_sale_price - total_cost - cod_service_charge

        # ✅ เช็คเกณฑ์ใหม่
        if (quantity_to_check == 1 and profit >= 150) or \
           (quantity_to_check == 2 and profit >= 300) or \
           (quantity_to_check == 4 and profit >= 600):
            return True, total_sale_price
        else:
            return False, None

    except (KeyError, ValueError, TypeError) as e:
        current_app.logger.error(f"Error checking stock and profit for {tire.get('model')}: {e}")
        return False, None

@api_key_required
@bp.route('/dialogflow', methods=['POST'])
def handle_dialogflow_request():
    req = request.get_json(force=True)
    intent_name = req.get('queryResult', {}).get('intent', {}).get('displayName')
    
    current_app.logger.info(f"Received intent: {intent_name}")
    current_app.logger.info(f"Full request: {json.dumps(req, indent=2)}")

    if intent_name == 'TirePriceCheck':
        return handle_tire_price_check(req)
    elif intent_name == 'SelectBrandAndQuantity':
        return handle_brand_selection(req)
    elif intent_name == 'SelectModel':
        return handle_model_selection(req)
    elif intent_name == 'ConfirmOrder':
        return handle_order_confirmation(req)
    elif intent_name == 'DeclineOrder':
        return handle_order_decline(req)
    elif intent_name == 'CollectCustomerInfo':
        return handle_collect_customer_info(req)
    elif intent_name == 'FinalSummary':
        return handle_final_summary(req)
    else:
        return jsonify({"fulfillmentText": "Webhook error: Unknown Intent"})

def handle_tire_price_check(dialogflow_request):
    parameters = dialogflow_request.get('queryResult', {}).get('parameters', {})
    tire_size = parameters.get('regex')

    if not tire_size:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ไม่พบข้อมูลเบอร์ยางที่ถูกต้อง"})

    try:
        headers = {'X-Api-Key': API_KEY}
        api_params = {'tire_query': tire_size}
        response = requests.get(TIRE_API_URL, params=api_params, headers=headers)
        response.raise_for_status()
        data = response.json()

        if data.get('status') == 'success' and data.get('results'):
            all_tires = data['results']
            
            # Filter tires to only show brands that have at least one profitable model with sufficient stock (for 4 tires as a standard)
            profitable_and_in_stock_brands = set()
            for tire in all_tires:
                ok_1, _ = check_stock_and_profit(tire, 1)
                ok_2, _ = check_stock_and_profit(tire, 2)
                ok_4, _ = check_stock_and_profit(tire, 4)

                if ok_1 or ok_2 or ok_4:
                    profitable_and_in_stock_brands.add(tire['brand'])
            
            if not profitable_and_in_stock_brands:
                return jsonify({"fulfillmentText": f"ขออภัยค่ะ ไม่พบยางเบอร์ {tire_size} ที่พร้อมจำหน่ายในสต็อกและทำกำไรได้ค่ะ"})

            brands = sorted(list(profitable_and_in_stock_brands))
            brand_text = ", ".join(brands)
            
            fulfillment_messages = [
                {
                    "text": {
                        "text": [f"เบอร์ยาง {tire_size} มียี่ห้อ {brand_text} ที่พร้อมจำหน่ายค่ะ สนใจยี่ห้อไหนดีคะ?"]
                    }
                },
                {
                    "payload": {
                        "richContent": [
                            [
                                {
                                    "type": "chips",
                                    "options": [{"text": brand} for brand in brands]
                                }
                            ]
                        ]
                    }
                }
            ]

            output_contexts = [{
                "name": f"{dialogflow_request['session']}/contexts/tireinfo",
                "lifespanCount": 5,
                "parameters": {
                    "tires_found": all_tires,
                    "original_tire_size": tire_size
                }
            }]
            return jsonify({
                "fulfillmentMessages": fulfillment_messages,
                "outputContexts": output_contexts
            })
        else:
            return jsonify({"fulfillmentText": f"ขออภัยค่ะ ไม่พบยางเบอร์ {tire_size} ในสต็อกค่ะ"})
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Webhook API call failed: {e}")
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ระบบสต็อกขัดข้องชั่วคราว"})

def handle_brand_selection(dialogflow_request):
    contexts = dialogflow_request.get('queryResult', {}).get('outputContexts', [])
    tire_info_context = next((c for c in contexts if c['name'].endswith('/contexts/tireinfo')), None)

    if not tire_info_context or 'parameters' not in tire_info_context or 'tires_found' not in tire_info_context['parameters']:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ข้อมูลยางเดิมหายไป กรุณาเริ่มต้นค้นหาใหม่อีกครั้งค่ะ"})

    all_tires = tire_info_context['parameters']['tires_found']
    parameters = dialogflow_request.get('queryResult', {}).get('parameters', {})

    selected_brand_param = parameters.get('brand_entity')
    if selected_brand_param:
        selected_brand = selected_brand_param[0] if isinstance(selected_brand_param, list) else selected_brand_param
    else:
        selected_brand = ""

    quantity_param = parameters.get('number', [1])
    if quantity_param:
        quantity = int(quantity_param[0]) if isinstance(quantity_param, list) and quantity_param else int(quantity_param)
    else:
        quantity = 1

    if not selected_brand:
        return jsonify({"fulfillmentText": "กรุณาระบุยี่ห้อที่ต้องการค่ะ"})

    matching_tires = [tire for tire in all_tires if tire.get('brand', '').lower() == selected_brand.lower()]
    
    available_tires_for_context = []
    for tire in matching_tires:
        is_profitable, total_price = check_stock_and_profit(tire, quantity)
        if is_profitable:
            available_tires_for_context.append({
                "brand": tire.get('brand'),
                "model": tire.get('model', '').strip(),
                "size": tire.get('size'),
                "quantity": quantity,
                "total_price": total_price
            })

    if available_tires_for_context:
        response_text = f"ยาง {selected_brand.title()} ขนาด {matching_tires[0].get('size','ไม่ระบุ')} มีรุ่นที่พร้อมจำหน่ายดังนี้ค่ะ:\n\n"
        for item in available_tires_for_context:
            response_text += f"- รุ่น {item['model']} ราคา {item['total_price']:,.2f} บาท ({item['quantity']} เส้น)\n"
        response_text += "\nกรุณาระบุรุ่นที่คุณต้องการจากรายการด้านบนได้เลยค่ะ"

    else:
        response_text = (
            f"ขออภัยค่ะ ยางยี่ห้อ {selected_brand.title()} สำหรับจำนวน {quantity} เส้น "
            f"ยังไม่มีรุ่นที่พร้อมจำหน่ายในขณะนี้ค่ะ"
        )
    
    tire_info_context['parameters']['quantity_selected'] = quantity
    tire_info_context['lifespanCount'] = 5

    return jsonify({
        "fulfillmentText": response_text,
        "outputContexts": [tire_info_context]
    })

def handle_model_selection(dialogflow_request):
    contexts = dialogflow_request.get('queryResult', {}).get('outputContexts', [])
    tire_info_context = next((c for c in contexts if c['name'].endswith('/contexts/tireinfo')), None)

    if not tire_info_context or 'parameters' not in tire_info_context or 'tires_found' not in tire_info_context['parameters']:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ข้อมูลยางเดิมหายไป กรุณาเริ่มต้นค้นหาใหม่อีกครั้งค่ะ"})

    tires_found = tire_info_context['parameters']['tires_found']
    parameters = dialogflow_request.get('queryResult', {}).get('parameters', {})
    
    selected_model_param = parameters.get('model_entity.original', parameters.get('model_entity', ''))
    
    normalized_user_model = normalize_string(selected_model_param)
    
    matching_model = next((tire for tire in tires_found if normalized_user_model in normalize_string(tire.get('model', ''))), None)

    if not matching_model:
        return jsonify({"fulfillmentText": f"ขออภัยค่ะ ไม่พบรุ่น {selected_model_param} ในรายการค่ะ"})
    
    quantity = tire_info_context['parameters'].get('quantity_selected', 4)

    is_profitable, total_price = check_stock_and_profit(matching_model, quantity)

    if not is_profitable:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ มีข้อผิดพลาดในการคำนวณราคาหรือสต็อกหมด กรุณาลองใหม่อีกครั้ง"})

    last_selection = {
        "brand": matching_model.get('brand'),
        "model": matching_model.get('model'),
        "size": matching_model.get('size'),
        "quantity": quantity,
        "total_price": total_price
    }
    
    tire_info_context['parameters']['last_selection'] = last_selection
    tire_info_context['lifespanCount'] = 5

    fulfillment_text = (
        f"คุณเลือกรุ่น {last_selection['model']} ({last_selection['size']}) จำนวน {last_selection['quantity']} เส้น "
        f"ยอดรวม {last_selection['total_price']:,.2f} บาท\n"
        f"ยืนยันการสั่งซื้อหรือไม่คะ?"
    )

    return jsonify({
        "fulfillmentText": fulfillment_text,
        "outputContexts": [tire_info_context]
    })

def handle_order_confirmation(dialogflow_request):
    contexts = dialogflow_request.get('queryResult', {}).get('outputContexts', [])
    tire_info_context = next((c for c in contexts if c['name'].endswith('/contexts/tireinfo')), None)

    if not tire_info_context or 'parameters' not in tire_info_context or 'last_selection' not in tire_info_context['parameters']:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ไม่พบข้อมูลการสั่งซื้อล่าสุด กรุณาเลือกสินค้าอีกครั้งค่ะ"})

    order_in_progress_context = {
        "name": f"{dialogflow_request['session']}/contexts/order_in_progress",
        "lifespanCount": 10,
        "parameters": tire_info_context['parameters']
    }
    
    fulfillment_text = "ได้รับคำยืนยันแล้วค่ะ! กรุณาแจ้งชื่อ, ที่อยู่, และเบอร์โทรศัพท์สำหรับจัดส่งสินค้าได้เลยค่ะ"

    return jsonify({
        "fulfillmentText": fulfillment_text,
        "outputContexts": [order_in_progress_context]
    })

def handle_order_decline(dialogflow_request):
    """Handles when a user declines the order."""
    return jsonify({"fulfillmentText": "รับทราบค่ะ หากต้องการค้นหายางใหม่แจ้งได้เลยนะคะ"})

def handle_collect_customer_info(dialogflow_request):
    contexts = dialogflow_request.get('queryResult', {}).get('outputContexts', [])
    order_in_progress_context = next((c for c in contexts if c['name'].endswith('/contexts/order_in_progress')), None)

    if not order_in_progress_context:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ข้อมูลการสั่งซื้อหายไป กรุณาเริ่มต้นใหม่อีกครั้ง"})

    parameters = dialogflow_request.get('queryResult', {}).get('parameters', {})
    
    customer_name = parameters.get('given-name')
    address = parameters.get('address-line')
    phone_number = parameters.get('phone-number')
    
    if not all([customer_name, address, phone_number]):
        return jsonify({"fulfillmentText": "ขออภัยค่ะ กรุณาแจ้งข้อมูล ชื่อ, ที่อยู่, และเบอร์โทรศัพท์ให้ครบถ้วนนะคะ"})

    order_in_progress_context['parameters']['customer_name'] = customer_name
    order_in_progress_context['parameters']['customer_address'] = address
    order_in_progress_context['parameters']['customer_phone'] = phone_number
    
    last_selection = order_in_progress_context['parameters']['last_selection']
    
    order_summary_text = (
        f"--- สรุปรายการสั่งซื้อ ---\n"
        f"สินค้า: ยางรถยนต์ {last_selection['brand']} รุ่น {last_selection['model']}\n"
        f"ขนาด: {last_selection['size']}\n"
        f"จำนวน: {last_selection['quantity']} เส้น\n"
        f"ยอดรวม: {last_selection['total_price']:,.2f} บาท\n\n"
        f"--- ข้อมูลจัดส่ง ---\n"
        f"ชื่อ: {customer_name}\n"
        f"ที่อยู่: {address}\n"
        f"เบอร์โทร: {phone_number}"
    )

    fulfillment_text = (
        f"✅ ได้รับข้อมูลเรียบร้อยแล้วค่ะ! กรุณาตรวจสอบข้อมูลอีกครั้งนะคะ\n\n"
        f"{order_summary_text}\n\n"
        f"หากข้อมูลถูกต้องทั้งหมด สามารถยืนยันคำสั่งซื้อได้เลยค่ะ"
    )

    order_in_progress_context['lifespanCount'] = 10
    
    return jsonify({
        "fulfillmentText": fulfillment_text,
        "outputContexts": [order_in_progress_context]
    })
    
def handle_final_summary(dialogflow_request):
    """Finalizes the order and notifies the admin."""
    contexts = dialogflow_request.get('queryResult', {}).get('outputContexts', [])
    order_in_progress_context = next((c for c in contexts if c['name'].endswith('/contexts/order_in_progress')), None)
    
    if not order_in_progress_context or 'customer_name' not in order_in_progress_context['parameters']:
        return jsonify({"fulfillmentText": "ขออภัยค่ะ ไม่พบข้อมูลการสั่งซื้อล่าสุด กรุณาเริ่มต้นใหม่อีกครั้ง"})
    
    last_selection = order_in_progress_context['parameters']['last_selection']
    customer_name = order_in_progress_context['parameters']['customer_name']
    customer_address = order_in_progress_context['parameters']['customer_address']
    customer_phone = order_in_progress_context['parameters']['customer_phone']
    
    final_summary_text = (
        f"--- สรุปคำสั่งซื้อสุดท้าย ---\n"
        f"สินค้า: ยาง {last_selection['brand']} รุ่น {last_selection['model']}\n"
        f"ขนาด: {last_selection['size']}\n"
        f"จำนวน: {last_selection['quantity']} เส้น\n"
        f"ยอดรวม: {last_selection['total_price']:,.2f} บาท\n"
        f"ชื่อ: {customer_name}\n"
        f"ที่อยู่: {customer_address}\n"
        f"เบอร์โทร: {customer_phone}"
    )
    
    fulfillment_text = (
        f"คำสั่งซื้อของคุณได้รับการยืนยันเรียบร้อยแล้ว ✅\n\n"
        f"{final_summary_text}\n\n"
        f"เดี๋ยวแอดมินจะรีบติดต่อกลับเพื่อยืนยันการจัดส่งอีกครั้งนะคะ ขอบคุณที่ใช้บริการค่ะ"
    )
    
    order_in_progress_context['lifespanCount'] = 0
    
    return jsonify({
        "fulfillmentText": fulfillment_text,
        "outputContexts": [order_in_progress_context]
    })