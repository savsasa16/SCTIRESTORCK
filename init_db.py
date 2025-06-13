# init_db_script.py
import os
import sys
import database # import database.py ของคุณ
from dotenv import load_dotenv

# โหลด environment variables จากไฟล์ .env ใน Local development
# บน Render จะโหลดจาก Environment Variables ที่ตั้งค่าไว้โดยตรง
load_dotenv() 

if __name__ == '__main__':
    conn = None
    try:
        print("Attempting to get database connection for initialization...")
        conn = database.get_db_connection()
        print("Connection successful. Initializing database tables...")
        
        # Call init_db() to create/check all tables
        database.init_db(conn) 
        print("Database tables created/checked successfully in Neon.")

        # ตรวจสอบและสร้าง Admin user หากยังไม่มี
        cursor = conn.cursor()
        
        # ใช้ %s สำหรับ PostgreSQL, ? สำหรับ SQLite
        is_postgres = "psycopg2" in str(type(conn))
        
        if is_postgres:
            cursor.execute("SELECT COUNT(*) AS count FROM users WHERE role = 'admin'")
        else:
            cursor.execute("SELECT COUNT(*) AS count FROM users WHERE role = 'admin'") # SQLite's Row factory handles 'count' key
        
        # เรียก fetchone() เพียงครั้งเดียวและเก็บผลลัพธ์
        admin_count_result = cursor.fetchone() 
        
        # ตรวจสอบว่ามีผลลัพธ์หรือไม่ และดึงค่า 'count' ออกมาอย่างปลอดภัย
        admin_count = admin_count_result['count'] if admin_count_result and 'count' in admin_count_result else 0
        
        if admin_count == 0:
            admin_username = "admin"
            # ใช้ค่าจาก ENV หรือ Default ที่รัดกุม (แนะนำให้ตั้งใน Render ENV)
            admin_initial_password = os.environ.get('ADMIN_INITIAL_PASSWORD', 'changeme123') 
            print(f"No admin user found. Creating default admin user: {admin_username} with initial password provided in ADMIN_INITIAL_PASSWORD.")
            
            # database.add_user จะทำการ commit ตัวเอง
            user_id = database.add_user(conn, admin_username, admin_initial_password, 'admin')
            if user_id:
                print(f"Admin user '{admin_username}' created successfully with ID: {user_id}")
            else:
                # กรณีนี้มักเกิดจากการที่ user มีอยู่แล้ว (อาจจะ race condition เล็กน้อย)
                print(f"Failed to create admin user '{admin_username}'. It might already exist (integrity constraint).")
        else:
            print("Admin user already exists. Skipping creation.")

        conn.commit() # Commit การเปลี่ยนแปลงอื่นๆ ที่อาจเกิดขึ้นใน init_db()
        print("Database initialization and admin user check complete.")

    except Exception as e:
        print(f"FATAL ERROR during database initialization: {e}", file=sys.stderr)
        if conn:
            conn.rollback() # ถ้ามี error ให้ rollback การเปลี่ยนแปลงทั้งหมด
        sys.exit(1) # Exit ด้วยสถานะ error เพื่อให้ Render ทราบว่า Build ล้มเหลว
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")
