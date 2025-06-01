import sqlite3
from datetime import datetime
import pytz
import re
from werkzeug.security import generate_password_hash, check_password_hash
import os
from urllib.parse import urlparse

# Import psycopg2 (ต้องติดตั้ง pip install psycopg2-binary)
try:
    import psycopg2
    # Optional: for fetching rows as dictionaries, similar to sqlite3.Row
    from psycopg2.extras import DictCursor
except ImportError:
    psycopg2 = None
    DictCursor = None
    print("psycopg2 not found. Running in SQLite mode only.")


def get_bkk_time():
    bkk_tz = pytz.timezone('Asia/Bangkok')
    return datetime.now(bkk_tz)

def get_db_connection():
    # ตรวจสอบว่ามี DATABASE_URL Environment Variable หรือไม่ (สำหรับ Production บน Render)
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if DATABASE_URL and psycopg2:
        # Connect to PostgreSQL
        try:
            url = urlparse(DATABASE_URL)
            conn = psycopg2.connect(
                database=url.path[1:],
                user=url.username,
                password=url.password,
                host=url.hostname,
                port=url.port,
                sslmode='require' # For Render, usually requires SSL
            )
            print("Connected to PostgreSQL database!")
            # เพื่อให้ยังสามารถเรียกใช้ row['column_name'] ได้เหมือน sqlite3.Row
            # เราจะ override row_factory ที่นี่
            # ถ้าต้องการใช้ DictCursor ให้สร้าง cursor ด้วย conn.cursor(cursor_factory=DictCursor) แทน
            # และตรวจสอบการใช้งานในฟังก์ชันอื่นๆ
            
            # Custom row_factory for psycopg2 to mimic sqlite3.Row
            def psycopg2_row_factory(cursor):
                column_names = [desc[0] for desc in cursor.description]
                def make_row(row):
                    return {col: val for col, val in zip(column_names, row)}
                return make_row
            
            conn.row_factory = psycopg2_row_factory
            return conn
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            # Fallback to SQLite if PostgreSQL connection fails, or raise error
            raise # Re-raise error if PostgreSQL is expected
    else:
        # Connect to SQLite (for Local Development)
        print("Connected to SQLite database (local development)!")
        conn = sqlite3.connect('inventory.db')
        conn.row_factory = sqlite3.Row # This allows accessing columns by name (e.g., row['column_name'])
        return conn

# Helper function to get date format for SQL query based on DB type
def get_sql_date_format_for_query(column_name):
    if os.environ.get('DATABASE_URL'): # If running on Render with PostgreSQL
        return f"TO_CHAR({column_name}, 'YYYY-MM-DD')"
    else: # If running locally with SQLite
        return f"STRFTIME('%Y-%m-%d', {column_name})"

def init_db(conn):
    cursor = conn.cursor()
    
    # ตรวจสอบว่ากำลังใช้ PostgreSQL หรือ SQLite
    is_postgres = "psycopg2" in str(type(conn))

    # SQL commands adjusted for PostgreSQL vs SQLite
    # Use SERIAL PRIMARY KEY for PostgreSQL for auto-incrementing ID
    # Use INTEGER PRIMARY KEY AUTOINCREMENT for SQLite
    
    # Promotions Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                type VARCHAR(255) NOT NULL,
                value1 FLOAT NOT NULL,
                value2 FLOAT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                value1 REAL NOT NULL,
                value2 REAL NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT NOT NULL
            );
        """)

    # Tires Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tires (
                id SERIAL PRIMARY KEY,
                brand VARCHAR(255) NOT NULL,
                model VARCHAR(255) NOT NULL,
                size VARCHAR(255) NOT NULL,
                quantity INTEGER DEFAULT 0,
                cost_sc FLOAT NULL, 
                cost_dunlop FLOAT NULL,
                cost_online FLOAT NULL,
                wholesale_price1 FLOAT NULL,
                wholesale_price2 FLOAT NULL,
                price_per_item FLOAT NOT NULL,
                promotion_id INTEGER NULL,
                year_of_manufacture VARCHAR(255) NULL,
                UNIQUE(brand, model, size),
                FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tires (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                size TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                cost_sc REAL NULL, 
                cost_dunlop REAL NULL,
                cost_online REAL NULL,
                wholesale_price1 REAL NULL,
                wholesale_price2 REAL NULL,
                price_per_item REAL NOT NULL,
                promotion_id INTEGER NULL,
                year_of_manufacture INTEGER NULL,
                UNIQUE(brand, model, size),
                FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL
            );
        """)

    # Wheels Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheels (
                id SERIAL PRIMARY KEY,
                brand VARCHAR(255) NOT NULL,
                model VARCHAR(255) NOT NULL,
                diameter FLOAT NOT NULL,
                pcd VARCHAR(255) NOT NULL,
                width FLOAT NOT NULL,
                et INTEGER NULL,
                color VARCHAR(255) NULL,
                quantity INTEGER DEFAULT 0,
                cost FLOAT NULL, 
                cost_online FLOAT NULL,
                wholesale_price1 FLOAT NULL,
                wholesale_price2 FLOAT NULL,
                retail_price FLOAT NOT NULL,
                image_filename VARCHAR(255) NULL,
                UNIQUE(brand, model, diameter, pcd, width, et, color)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                diameter REAL NOT NULL,
                pcd TEXT NOT NULL,
                width REAL NOT NULL,
                et INTEGER NULL,
                color TEXT NULL,
                quantity INTEGER DEFAULT 0,
                cost REAL NULL, 
                cost_online REAL NULL,
                wholesale_price1 REAL NULL,
                wholesale_price2 REAL NULL,
                retail_price REAL NOT NULL,
                image_filename TEXT NULL,
                UNIQUE(brand, model, diameter, pcd, width, et, color)
            );
        """)

    # Tire Movements Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_movements (
                id SERIAL PRIMARY KEY,
                tire_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                FOREIGN KEY (tire_id) REFERENCES tires(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tire_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                FOREIGN KEY (tire_id) REFERENCES tires(id)
            );
        """)

    # Wheel Movements Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_movements (
                id SERIAL PRIMARY KEY,
                wheel_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheel_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id)
            );
        """)

    # Wheel Fitments Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_fitments (
                id SERIAL PRIMARY KEY,
                wheel_id INTEGER NOT NULL,
                brand VARCHAR(255) NOT NULL,
                model VARCHAR(255) NOT NULL,
                year_start INTEGER NOT NULL,
                year_end INTEGER NULL,
                UNIQUE(wheel_id, brand, model, year_start, year_end),
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_fitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheel_id INTEGER NOT NULL,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                year_start INTEGER NOT NULL,
                year_end INTEGER NULL,
                UNIQUE(wheel_id, brand, model, year_start, year_end),
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)

    # Users Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'viewer'
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer'
            );
        """)
    conn.commit()

# --- User Model (Modified to include role and permission checks) ---
class User:
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = role # NEW: Store role

    @staticmethod
    def get(conn, user_id):
        # Use PARAMETERIZED queries to prevent SQL injection
        cursor = conn.execute("SELECT id, username, password, role FROM users WHERE id = %s", (user_id,)) if "psycopg2" in str(type(conn)) else conn.execute("SELECT id, username, password, role FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            return User(user_data['id'], user_data['username'], user_data['password'], user_data['role'])
        return None

    @staticmethod
    def get_by_username(conn, username):
        # Use PARAMETERIZED queries
        cursor = conn.execute("SELECT id, username, password, role FROM users WHERE username = %s", (username,)) if "psycopg2" in str(type(conn)) else conn.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        if user_data:
            return User(user_data['id'], user_data['username'], user_data['password'], user_data['role'])
        return None
    
    # Flask-Login required properties
    def is_active(self):
        return True

    def is_authenticated(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

    # --- NEW: Permission Checkers ---
    def is_admin(self):
        return self.role == 'admin'

    def can_edit(self):
        return self.role in ['admin', 'editor']

    def can_view(self):
        return self.role in ['admin', 'editor', 'viewer']

# --- User Management Functions (Modified for role) ---
def add_user(conn, username, password, role='viewer'): # NEW: Default role for new users
    hashed_password = generate_password_hash(password)
    cursor = conn.cursor()
    try:
        if "psycopg2" in str(type(conn)):
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s) RETURNING id", (username, hashed_password, role))
            user_id = cursor.fetchone()['id']
        else:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed_password, role))
            user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except (sqlite3.IntegrityError, Exception) as e:
        # Catch psycopg2.errors.UniqueViolation for PostgreSQL
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
            return None # Username already exists
        else:
            raise # Re-raise other exceptions

def update_user_role(conn, user_id, new_role): # NEW: Function to update user role
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
    else:
        cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()

# --- Promotion Functions ---
def add_promotion(conn, name, promo_type, value1, value2, is_active):
    created_at = get_bkk_time().isoformat()
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO promotions (name, type, value1, value2, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (name, promo_type, value1, value2, is_active, created_at))
        promo_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO promotions (name, type, value1, value2, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, promo_type, value1, value2, is_active, created_at))
        promo_id = cursor.lastrowid
    conn.commit()
    return promo_id

def get_promotion(conn, promo_id):
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute("SELECT * FROM promotions WHERE id = %s", (promo_id,))
    else:
        cursor = conn.execute("SELECT * FROM promotions WHERE id = ?", (promo_id,))
    return cursor.fetchone()

def get_all_promotions(conn, include_inactive=False):
    sql_query = "SELECT * FROM promotions"
    params = []
    if not include_inactive:
        sql_query += " WHERE is_active = TRUE" if "psycopg2" in str(type(conn)) else " WHERE is_active = 1"
    sql_query += " ORDER BY name"
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute(sql_query, params)
    else:
        cursor = conn.execute(sql_query, params)
    return cursor.fetchall()

def update_promotion(conn, promo_id, name, promo_type, value1, value2, is_active):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE promotions SET
                name = %s,
                type = %s,
                value1 = %s,
                value2 = %s,
                is_active = %s
            WHERE id = %s
        """, (name, promo_type, value1, value2, is_active, promo_id))
    else:
        cursor.execute("""
            UPDATE promotions SET
                name = ?,
                type = ?,
                value1 = ?,
                value2 = ?,
                is_active = ?
            WHERE id = ?
        """, (name, promo_type, value1, value2, is_active, promo_id))
    conn.commit()

def delete_promotion(conn, promo_id):
    if "psycopg2" in str(type(conn)):
        conn.execute("UPDATE tires SET promotion_id = NULL WHERE promotion_id = %s", (promo_id,))
        conn.execute("DELETE FROM promotions WHERE id = %s", (promo_id,))
    else:
        conn.execute("UPDATE tires SET promotion_id = NULL WHERE promotion_id = ?", (promo_id,))
        conn.execute("DELETE FROM promotions WHERE id = ?", (promo_id,))
    conn.commit()

# --- Tire Functions (Modified) ---
def add_tire(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.lastrowid
    conn.commit()
    return tire_id

def get_tire(conn, tire_id):
    # Use parameterized queries for both SQLite and PostgreSQL
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute("""
            SELECT t.*, 
                   p.name AS promo_name, 
                   p.type AS promo_type, 
                   p.value1 AS promo_value1, 
                   p.value2 AS promo_value2,
                   p.is_active AS promo_is_active
            FROM tires t
            LEFT JOIN promotions p ON t.promotion_id = p.id
            WHERE t.id = %s
        """, (tire_id,))
    else:
        cursor = conn.execute("""
            SELECT t.*, 
                   p.name AS promo_name, 
                   p.type AS promo_type, 
                   p.value1 AS promo_value1, 
                   p.value2 AS promo_value2,
                   p.is_active AS promo_is_active
            FROM tires t
            LEFT JOIN promotions p ON t.promotion_id = p.id
            WHERE t.id = ?
        """, (tire_id,))
    tire = cursor.fetchone()
    
    if tire:
        # If using custom row_factory for psycopg2, tire is already dict-like.
        # Otherwise, if it's a tuple, convert it to a dict first if needed.
        # With the psycopg2_row_factory, tire will be a dict.
        tire_dict = dict(tire) if not isinstance(tire, dict) else tire
        
        tire_dict['display_promo_price_per_item'] = None # Default to None
        tire_dict['display_price_for_4'] = tire_dict['price_per_item'] * 4 if tire_dict['price_per_item'] is not None else None # Default for 4 items
        tire_dict['display_promo_description'] = None # Default description

        # PostgreSQL BOOLEANs are fetched as True/False, SQLite as 0/1
        promo_active_check = tire_dict['promo_is_active']
        if "psycopg2" in str(type(conn)):
            promo_active_check = bool(promo_active_check) # Ensure boolean for psycopg2
        else:
            promo_active_check = (promo_active_check == 1) # Ensure boolean for sqlite

        if tire_dict['promotion_id'] is not None and promo_active_check:
            promo_calc_result = calculate_tire_promo_prices(
                tire_dict['price_per_item'],
                tire_dict['promo_type'],
                tire_dict['promo_value1'],
                tire_dict['promo_value2']
            )
            tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
            tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
            tire_dict['display_promo_description'] = promo_calc_result['promo_description_text']
        
        return tire_dict 
    return tire

def update_tire(conn, tire_id, brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE tires SET
                brand = %s,
                model = %s,
                size = %s,
                cost_sc = %s,
                cost_dunlop = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                price_per_item = %s,
                promotion_id = %s,
                year_of_manufacture = %s
            WHERE id = %s
        """, (brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    else:
        cursor.execute("""
            UPDATE tires SET
                brand = ?,
                model = ?,
                size = ?,
                cost_sc = ?,
                cost_dunlop = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                price_per_item = ?,
                promotion_id = ?,
                year_of_manufacture = ?
            WHERE id = ?
        """, (brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    conn.commit()

# Function for Import from Excel (updated for promotion_id and price_per_item)
def add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture): 
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.lastrowid
    conn.commit()
    return tire_id

def update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture): 
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE tires SET
                brand = %s,
                model = %s,
                size = %s,
                quantity = %s, 
                cost_sc = %s,
                cost_dunlop = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                price_per_item = %s,
                promotion_id = %s,
                year_of_manufacture = %s
            WHERE id = %s
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    else:
        cursor.execute("""
            UPDATE tires SET
                brand = ?,
                model = ?,
                size = ?,
                quantity = ?, 
                cost_sc = ?,
                cost_dunlop = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                price_per_item = ?,
                promotion_id = ?,
                year_of_manufacture = ?
            WHERE id = ?
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    conn.commit()

# NEW: Unified function to calculate prices for display based on promo type
def calculate_tire_promo_prices(price_per_item, promo_type, promo_value1, promo_value2):
    price_per_item_promo = price_per_item
    price_for_4_promo = price_per_item * 4
    promo_description_text = None

    if price_per_item is None or promo_type is None:
        return {
            'price_per_item_promo': None, 
            'price_for_4_promo': price_per_item * 4 if price_per_item is not None else None,
            'promo_description_text': None
        }

    if promo_type == 'buy_x_get_y' and promo_value1 is not None and promo_value2 is not None:
        if (promo_value1 > 0 and promo_value2 >= 0):
            # Price for (X + Y) items = price_per_item * X
            # Price per item (promo) = (price_per_item * X) / (X + Y)
            # Price for 4 items (promo) = price_per_item_promo * 4
            if (promo_value1 + promo_value2) > 0: # Avoid division by zero
                price_per_item_promo = (price_per_item * promo_value1) / (promo_value1 + promo_value2)
                price_for_4_promo = price_per_item_promo * 4
                promo_description_text = f"ซื้อ {int(promo_value1)} แถม {int(promo_value2)} ฟรี"
            else: # If X+Y is 0, promo is invalid
                price_per_item_promo = None
                price_for_4_promo = None
                promo_description_text = "โปรไม่ถูกต้อง (X+Y=0)"
        else: # Invalid X or Y
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (X,Y<=0)"
    
    elif promo_type == 'percentage_discount' and promo_value1 is not None:
        if (promo_value1 >= 0 and promo_value1 <= 100):
            price_per_item_promo = price_per_item * (1 - (promo_value1 / 100))
            price_for_4_promo = price_per_item_promo * 4
            promo_description_text = f"ลด {promo_value1}%"
        else: # Invalid percentage
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (%ไม่ถูกต้อง)"
    
    elif promo_type == 'fixed_price_per_n' and promo_value1 is not None and promo_value2 is not None:
        # promo_value1 is fixed price for promo_value2 items
        # Example: 3 items for $2900 (Value1=2900, Value2=3)
        if promo_value2 > 0:
            price_per_item_promo = promo_value1 / promo_value2
            price_for_4_promo = price_per_item_promo * 4
            promo_description_text = f"ราคา {promo_value1:.2f} บาท สำหรับ {int(promo_value2)} เส้น"
        else: # Invalid N
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (N<=0)"
            
    # Fallback to normal price if promo type is not recognized or values are invalid
    if price_per_item_promo is None:
        price_per_item_promo = price_per_item
        price_for_4_promo = price_per_item * 4
        promo_description_text = None

    return {
        'price_per_item_promo': price_per_item_promo, 
        'price_for_4_promo': price_for_4_promo,
        'promo_description_text': promo_description_text
    }


def get_all_tires(conn, query=None, brand_filter='all'):
    sql_query = """
        SELECT t.*,
               p.name AS promo_name,
               p.type AS promo_type,
               p.value1 AS promo_value1,
               p.value2 AS promo_value2,
               p.is_active AS promo_is_active
        FROM tires t
        LEFT JOIN promotions p ON t.promotion_id = p.id
    """
    params = []
    conditions = []

    if query:
        search_term = f"%{query}%"
        conditions.append("(t.brand ILIKE %s OR t.model ILIKE %s OR t.size ILIKE %s)" if "psycopg2" in str(type(conn)) else "(t.brand LIKE ? OR t.model LIKE ? OR t.size LIKE ?)")
        params.extend([search_term, search_term, search_term])

    if brand_filter != 'all':
        conditions.append("t.brand = %s" if "psycopg2" in str(type(conn)) else "t.brand = ?")
        params.append(brand_filter)

    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)

    sql_query += " ORDER BY t.brand, t.model"

    if "psycopg2" in str(type(conn)):
        cursor = conn.execute(sql_query, params)
    else:
        cursor = conn.execute(sql_query, params)

    tires = cursor.fetchall()

    processed_tires = []
    for tire in tires:
        # Ensure tire is a dictionary (for both SQLite.Row and psycopg2_row_factory)
        tire_dict = dict(tire) if not isinstance(tire, dict) else tire

        # Calculate display prices for each tire
        promo_calc_result = {
            'price_per_item_promo': None,
            'price_for_4_promo': tire_dict['price_per_item'] * 4 if tire_dict['price_per_item'] is not None else None,
            'promo_description_text': None
        }

        # PostgreSQL BOOLEANs are fetched as True/False, SQLite as 0/1
        promo_active_check = tire_dict['promo_is_active']
        if "psycopg2" in str(type(conn)):
            promo_active_check = bool(promo_active_check)
        else:
            promo_active_check = (promo_active_check == 1)

        if tire_dict['promotion_id'] is not None and promo_active_check:
            promo_calc_result = calculate_tire_promo_prices(
                tire_dict['price_per_item'],
                tire_dict['promo_type'],
                tire_dict['promo_value1'],
                tire_dict['promo_value2']
            )

        tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
        tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
        tire_dict['display_promo_description_text'] = promo_calc_result['promo_description_text']

        processed_tires.append(tire_dict)

    def sort_key_for_tire_size(tire_item):
        size_str = tire_item.get('size', '')
        # Use Regular Expression เพื่อหาตัวเลขที่อยู่หลัง 'R' หรือตัวเลขท้ายสุด
        match = re.search(r'R(\d+)$', size_str) # เช่น '215/65R16' -> 16
        if not match:
            # ลองหาตัวเลขท้ายสุดเฉยๆ ถ้าไม่มี 'R' (บางทีอาจเป็นแค่ '14', '15')
            match = re.search(r'(\d+)$', size_str)

        try:
            # ถ้าเจอตัวเลข ให้แปลงเป็น int เพื่อเรียงลำดับแบบตัวเลข
            rim_size = int(match.group(1)) if match else 0
            return rim_size
        except ValueError:
            # ถ้าแปลงไม่ได้ หรือไม่เจอตัวเลข ให้คืนค่า 0 หรือค่าอื่นที่เหมาะสม
            return 0
    
    sorted_processed_tires = sorted(processed_tires, key=lambda x: (x.get('brand', ''), x.get('model', ''), sort_key_for_tire_size(x)))

    return sorted_processed_tires

def update_tire_quantity(conn, tire_id, new_quantity):
    if "psycopg2" in str(type(conn)):
        conn.execute("UPDATE tires SET quantity = %s WHERE id = %s", (new_quantity, tire_id))
    else:
        conn.execute("UPDATE tires SET quantity = ? WHERE id = ?", (new_quantity, tire_id))
    conn.commit()

def add_tire_movement(conn, tire_id, move_type, quantity_change, remaining_quantity, notes):
    timestamp = get_bkk_time().isoformat()
    if "psycopg2" in str(type(conn)):
        conn.execute("""
            INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (tire_id, timestamp, move_type, quantity_change, remaining_quantity, notes))
    else:
        conn.execute("""
            INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tire_id, timestamp, move_type, quantity_change, remaining_quantity, notes))
    conn.commit()

def delete_tire(conn, tire_id):
    if "psycopg2" in str(type(conn)):
        conn.execute("DELETE FROM tires WHERE id = %s", (tire_id,))
    else:
        conn.execute("DELETE FROM tires WHERE id = ?", (tire_id,))
    conn.commit()

def get_all_tire_brands(conn):
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute("SELECT DISTINCT brand FROM tires ORDER BY brand")
    else:
        cursor = conn.execute("SELECT DISTINCT brand FROM tires ORDER BY brand")
    return [row['brand'] for row in cursor.fetchall()]

# --- Wheel Functions ---
def get_all_wheels(conn, query=None, brand_filter='all'):
    sql_query = "SELECT * FROM wheels"
    params = []
    conditions = []

    if "psycopg2" in str(type(conn)):
        if query:
            search_term = f"%{query}%"
            conditions.append("(brand ILIKE %s OR model ILIKE %s OR pcd ILIKE %s OR color ILIKE %s)")
            params.extend([search_term, search_term, search_term, search_term])
        
        if brand_filter != 'all':
            conditions.append("brand = %s")
            params.append(brand_filter)
    else: # SQLite
        if query:
            search_term = f"%{query}%"
            conditions.append("(brand LIKE ? OR model LIKE ? OR pcd LIKE ? OR color LIKE ?)")
            params.extend([search_term, search_term, search_term, search_term])
        
        if brand_filter != 'all':
            conditions.append("brand = ?")
            params.append(brand_filter)
    
    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)
    
    sql_query += " ORDER BY brand, model, diameter"
    
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute(sql_query, params)
    else:
        cursor = conn.execute(sql_query, params)
    return cursor.fetchall()

def get_wheel(conn, wheel_id):
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute("SELECT * FROM wheels WHERE id = %s", (wheel_id,))
    else:
        cursor = conn.execute("SELECT * FROM wheels WHERE id = ?", (wheel_id,))
    return cursor.fetchone()

def add_wheel(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename))
        wheel_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename))
        wheel_id = cursor.lastrowid
    conn.commit()
    return wheel_id

def update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE wheels SET
                brand = %s,
                model = %s,
                diameter = %s,
                pcd = %s,
                width = %s,
                et = %s,
                color = %s,
                cost = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                retail_price = %s,
                image_filename = %s
            WHERE id = %s
        """, (brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, wheel_id))
    else:
        cursor.execute("""
            UPDATE wheels SET
                brand = ?,
                model = ?,
                diameter = ?,
                pcd = ?,
                width = ?,
                et = ?,
                color = ?,
                cost = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                retail_price = ?,
                image_filename = ?
            WHERE id = ?
        """, (brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, wheel_id))
    conn.commit()

def add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename))
        wheel_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename))
        wheel_id = cursor.lastrowid
    conn.commit()
    return wheel_id

def update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE wheels SET
                brand = %s,
                model = %s,
                diameter = %s,
                pcd = %s,
                width = %s,
                et = %s,
                color = %s,
                quantity = %s,
                cost = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                retail_price = %s,
                image_filename = %s
            WHERE id = %s
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, wheel_id))
    else:
        cursor.execute("""
            UPDATE wheels SET
                brand = ?,
                model = ?,
                diameter = ?,
                pcd = ?,
                width = ?,
                et = ?,
                color = ?,
                quantity = ?,
                cost = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                retail_price = ?,
                image_filename = ?
            WHERE id = ?
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, wheel_id))
    conn.commit()

def delete_wheel(conn, wheel_id):
    if "psycopg2" in str(type(conn)):
        conn.execute("DELETE FROM wheels WHERE id = %s", (wheel_id,))
    else:
        conn.execute("DELETE FROM wheels WHERE id = ?", (wheel_id,))
    conn.commit()

def get_all_wheel_brands(conn):
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute("SELECT DISTINCT brand FROM wheels ORDER BY brand")
    else:
        cursor = conn.execute("SELECT DISTINCT brand FROM wheels ORDER BY brand")
    return [row['brand'] for row in cursor.fetchall()]

def add_wheel_fitment(conn, wheel_id, brand, model, year_start, year_end):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO wheel_fitments (wheel_id, brand, model, year_start, year_end)
            VALUES (%s, %s, %s, %s, %s)
        """, (wheel_id, brand, model, year_start, year_end))
    else:
        cursor.execute("""
            INSERT INTO wheel_fitments (wheel_id, brand, model, year_start, year_end)
            VALUES (?, ?, ?, ?, ?)
        """, (wheel_id, brand, model, year_start, year_end))
    conn.commit()

def get_wheel_fitments(conn, wheel_id):
    if "psycopg2" in str(type(conn)):
        cursor = conn.execute("SELECT * FROM wheel_fitments WHERE wheel_id = %s ORDER BY brand, model, year_start", (wheel_id,))
    else:
        cursor = conn.execute("SELECT * FROM wheel_fitments WHERE wheel_id = ? ORDER BY brand, model, year_start", (wheel_id,))
    return cursor.fetchall()

def delete_wheel_fitment(conn, fitment_id):
    if "psycopg2" in str(type(conn)):
        conn.execute("DELETE FROM wheel_fitments WHERE id = %s", (fitment_id,))
    else:
        conn.execute("DELETE FROM wheel_fitments WHERE id = ?", (fitment_id,))
    conn.commit()