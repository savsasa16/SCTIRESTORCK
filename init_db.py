import os
import database
from flask import Flask
from dotenv import load_dotenv

load_dotenv() # Load environment variables for local testing

app = Flask(__name__) # Create a minimal Flask app context
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default_secret_key') # Just needs to be defined

# You need app_context for g.db to work properly
# If get_db_connection() doesn't rely on g, you can remove Flask context
# But using it is safer for consistency with app.py
with app.app_context():
    conn = database.get_db_connection()
    try:
        print("Initializing database...")
        database.init_db(conn)
        print("Database initialization complete. Checking for initial admin user...")

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        if user_count == 0:
            admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'adminpassword')
            database.add_user(conn, admin_username, admin_password, role='admin')
            print(f"Initial admin user '{admin_username}' created with password '{admin_password}' and role 'admin'.")
        else:
            print(f"Users table already has {user_count} entries. Skipping initial admin user creation.")

        conn.commit() # Ensure all changes are saved
        print("Database operations committed.")

    except Exception as e:
        print(f"Error during database initialization: {e}")
        if conn:
            conn.rollback() # Rollback any partial changes
        raise # Re-raise the exception to indicate failure
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")