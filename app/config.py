import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'library-system-pro-dev-key-2024'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///library.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    DEBUG = False
    TESTING = False
    PROPAGATE_EXCEPTIONS = True
    JSON_SORT_KEYS = False
    APP_NAME = "library os"
    APP_VERSION = "1.0"
    COMPANY_NAME = "Your Library"
    SUPPORT_EMAIL = "support@yourlibrary.com"
    FINE_AMOUNT_PER_DAY = 5
    CURRENCY_SYMBOL = "PKR"
    DEFAULT_LOAN_DURATION = 10
    MIN_LOAN_DURATION = 1
    MAX_LOAN_DURATION = 30
    DEFAULT_COPIES = 1
    ALLOW_NEGATIVE_STOCK = False
    MIN_PASSWORD_LENGTH = 6
    REQUIRE_SPECIAL_CHARS = False
    REQUIRE_NUMBERS = False
    ITEMS_PER_PAGE = 20
    MAX_ITEMS_PER_PAGE = 100
    PASSWORD_HASH_METHOD = 'werkzeug'
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URL = 'memory://'
    FEATURES = {
        'digital_books': True,
        'wishlist': True,
        'activity_logging': True,
        'email_notifications': False,
        'sms_notifications': False,
        'barcode_scanning': False,
    }
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', False)
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', False)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@library.com')
    LOG_LEVEL = 'INFO'
    LOG_FILE = 'logs/library.log'
    LOG_MAX_SIZE = 10485760
    LOG_BACKUP_COUNT = 10
    LOGO_PATH = '/static/images/logo.png'
    FAVICON_PATH = '/static/images/favicon.ico'
    THEME_COLOR = '#667eea'
    ADMIN_PANEL_ENABLED = True
    ALLOW_USER_REGISTRATION = False
    REQUIRE_ADMIN_APPROVAL = False
    AUTO_BACKUP_ENABLED = False
    BACKUP_INTERVAL_DAYS = 7
    BACKUP_DIRECTORY = 'backups/'


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable not set for production!")


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])
