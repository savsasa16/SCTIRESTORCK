# main.py
from app import create_app
from dotenv import load_dotenv
import os

# ต้องเรียกใช้ load_dotenv() ก่อนการสร้าง app
# เพื่อให้ค่าจาก .env ถูกโหลดก่อนที่ sentry จะถูกเรียกใช้
load_dotenv() 

# Call the factory function to create our app instance
app = create_app()

# This is the standard entry point for running the app
if __name__ == '__main__':
    # The host='0.0.0.0' makes the server accessible from other devices on your network
    # debug=False will allow Sentry to capture errors
    app.run(host='0.0.0.0', port=5000, debug=True)