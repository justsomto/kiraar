import os
from dotenv import load_dotenv

# Load variables from .env file into environment
load_dotenv()

def _fix_postgres_url(url):
    """Render gives 'postgres://' but SQLAlchemy needs 'postgresql://'"""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url

class GeneralConfig(object): 
    SECRET_KEY = os.environ.get('SECRET_KEY', 'sample-secret-key')
    # Render/Railway provide DATABASE_URL (PostgreSQL). Locally we use MySQL.
    SQLALCHEMY_DATABASE_URI = _fix_postgres_url(os.environ.get('DATABASE_URL')) or \
                              os.environ.get('SQLALCHEMY_DATABASE_URI', 'mysql+mysqlconnector://root@localhost/kiraardb')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Base URL of the app — used in email links. Set this in your cloud env vars.
    APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://127.0.0.1:5057')

    # CometChat credentials
    COMETCHAT_APP_ID = os.environ.get('COMETCHAT_APP_ID', '1680989b66300858c')
    COMETCHAT_REGION = os.environ.get('COMETCHAT_REGION', 'eu')
    COMETCHAT_AUTH_KEY = os.environ.get('COMETCHAT_AUTH_KEY', '')
    
    # Paystack credentials
    PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
    PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')

    # Gmail SMTP config
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', '')

    # Google OAuth credentials
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

class LiveConfig(GeneralConfig):
    SECRET_KEY = os.environ.get('SECRET_KEY', '18eef3b4e273a4d623971f5fdd1a91a7eedc7d6224f08a86b0d7e0db6f3908d7')