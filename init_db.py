# init_db_script.py
import os
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
        database.init_db(conn)
        print("Database tables created/checked successfully in Neon.")

        # ตรวจสอบและสร้าง Admin user หากยังไม่มี (เป็นส่วนสำคัญสำหรับการเข้าสู่ระบบครั้งแรก)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admin_count = cursor.fetchone()['count'] if isinstance(cursor.fetchone(), dict) else cursor.fetchone()[0] # Adjust for DictCursor vs normal fetchone

        if admin_count == 0:
            admin_username = "admin"
            admin_initial_password = os.environ.get('ADMIN_INITIAL_PASSWORD', 'changeme123') # ใช้ค่าจาก ENV หรือ Default
            print(f"No admin user found. Creating default admin user: {admin_username}")
            user_id = database.add_user(conn, admin_username, admin_initial_password, 'admin')
            if user_id:
                print(f"Admin user '{admin_username}' created successfully.")
            else:
                print(f"Failed to create admin user '{admin_username}'. It might already exist (race condition).")
        else:
            print("Admin user already exists. Skipping creation.")

        conn.commit() # Ensure all changes are committed
        print("Database initialization and admin user check complete.")

    except Exception as e:
        print(f"FATAL ERROR during database initialization: {e}", flush=True)
        # Re-raise the exception to make Render's build fail if DB init fails
        raise
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")
