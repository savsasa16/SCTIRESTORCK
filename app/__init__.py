import os
from functools import wraps
from flask import Flask, g, request, jsonify, redirect, url_for
from flask_login import LoginManager, current_user
from flask_caching import Cache
from datetime import timedelta
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

# Import database functions and User class from the root directory
import database
from database import User 

# Cloudinary setting
import cloudinary
import cloudinary.uploader

# Create extension objects but don't configure them yet
cache = Cache()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

CORRECT_API_KEY = os.getenv("API_SECRET_KEY")

if CORRECT_API_KEY:
    print("✅ API_SECRET_KEY is successfully loaded.")
else:
    print("❌ API_SECRET_KEY is missing from environment variables.")

def api_key_required(f):
    """
    Decorator to check for a valid API Key in the request header.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        incoming_api_key = request.headers.get('X-Api-Key')
        
        # ตรวจสอบว่าค่า API Key ใน .env ถูกโหลดมาหรือไม่
        if not CORRECT_API_KEY:
            # นี่คือกรณีที่ค่าใน .env ไม่ถูกโหลดมา
            return jsonify({"error": "Server configuration error"}), 500

        # ตรวจสอบว่า API Key ที่ส่งมาถูกต้องหรือไม่
        if incoming_api_key and incoming_api_key == CORRECT_API_KEY:
            return f(*args, **kwargs)
        
        return jsonify({"error": "Unauthorized: Invalid or missing API key"}), 401

    return decorated_function

def get_db():
        if 'db' not in g:
            g.db = database.get_db_connection()
        return g.db    

def create_app():
    """
    This is the application factory function.
    """
    app = Flask(__name__, instance_relative_config=True)

    # --- Basic App Configuration ---
    app.secret_key = os.environ.get('SECRET_KEY', 'a_very_strong_secret_key_should_be_here')
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.jinja_env.add_extension('jinja2.ext.do')

    # --- Caching Configuration ---
    if os.environ.get('REDIS_URL'):
        app.config.from_mapping(
            CACHE_TYPE="RedisCache",
            CACHE_REDIS_URL=os.environ.get('REDIS_URL')
        )
        print("✅ Redis is configured for caching.")
    else:
        app.config.from_mapping(CACHE_TYPE="SimpleCache")
        print("🔧 SimpleCache is configured for local development.")


    if os.environ.get('CLOUDINARY_CLOUD_NAME'):
        # Configure Cloudinary if all necessary environment variables are present
        app.config['CLOUDINARY_AVAILABLE'] = True
        cloudinary.config(
            cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
            api_key=os.environ.get('CLOUDINARY_API_KEY'),
            api_secret=os.environ.get('CLOUDINARY_API_SECRET')
        )
        print("✅ Cloudinary is configured and available.")
    else:
        app.config['CLOUDINARY_AVAILABLE'] = False
        print("🔧 Cloudinary configuration not found. Will use local storage.")

    # --- Sentry Configuration ---
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            traces_sample_rate=1.0,
            # Set profile_session_sample_rate to 1.0 to profile 100%
            # of profile sessions.
            profile_session_sample_rate=1.0,
            # Set profile_lifecycle to "trace" to automatically
            # run the profiler on when there is an active transaction
            profile_lifecycle="trace"
        )
        print("✅ Sentry is configured and enabled.")
    else:
        print("🔧 SENTRY_DSN not found. Sentry will not be enabled.")


    # Initialize extensions with the app
    cache.init_app(app)
    login_manager.init_app(app)

    # --- START: Global Functions & Context Processor ---
    # We define these inside create_app to associate them with the app instance.

    @cache.memoize(timeout=300)
    def get_cached_unread_notification_count():
        conn = get_db()
        # Ensure the connection is not closed prematurely
        count = database.get_unread_notification_count(conn)
        return count

    @app.context_processor
    def inject_global_data():
        unread_count = 0
        latest_announcement = None
        if current_user.is_authenticated:
            try:
                unread_count = get_cached_unread_notification_count()
                conn = get_db()
                latest_announcement = database.get_latest_active_announcement(conn)
            except Exception as e:
                print(f"Error in context processor: {e}")
        
        return dict(
            get_bkk_time=database.get_bkk_time,
            unread_notification_count=unread_count,
            latest_announcement=latest_announcement
        )
    # --- END: Global Functions & Context Processor ---


    # --- User Loader for Flask-Login ---
    @login_manager.user_loader
    def load_user(user_id):
        conn = database.get_db_connection()
        user = User.get(conn, user_id)
        conn.close()
        return user

    # --- Teardown Context for Database Connection ---
    @app.teardown_appcontext
    def close_db(e=None):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.after_request
    def log_activity(response):
        # 1. ไม่บันทึก Log สำหรับไฟล์ static และ API บางตัวที่ไม่สำคัญ
        if not current_user.is_authenticated or \
        not request.endpoint or \
        request.endpoint.startswith('static') or \
        'api_search' in request.endpoint: # ไม่ต้อง log ทุกครั้งที่พิมพ์ค้นหา
            return response
        
        try:
            conn = get_db()
            database.add_activity_log(
                conn,
                user_id=current_user.id,
                endpoint=request.endpoint,
                method=request.method,
                url=request.path # แก้จาก request.url เป็น request.path เพื่อให้สั้นลง
            )
            conn.commit()
        except Exception as e:
            print(f"CRITICAL: Error logging activity: {e}")
            # ไม่ต้อง rollback เพราะอาจทำให้ transaction อื่นรวนได้

        return response       

    # --- Register Blueprints (The Modules) ---
    with app.app_context():
        from . import stock
        app.register_blueprint(stock.bp)

        from . import auth
        app.register_blueprint(auth.bp)

        from . import selector
        app.register_blueprint(selector.bp)

        from . import service
        app.register_blueprint(service.bp)

        from . import webhook
        app.register_blueprint(webhook.bp)

    @app.route("/sentry-debug")
    def sentry_debug():
        raise Exception("This is a test error from Flask!")

    return app