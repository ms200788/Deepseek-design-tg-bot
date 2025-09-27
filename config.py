import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    OWNER_ID = int(os.getenv('OWNER_ID', 0))
    DATABASE_URL = os.getenv('DATABASE_URL')
    UPLOAD_CHANNEL_ID = os.getenv('UPLOAD_CHANNEL_ID')
    
    WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL')
    WEBHOOK_PATH = '/webhook'
    WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None
    
    WEBAPP_HOST = '0.0.0.0'
    WEBAPP_PORT = int(os.getenv('PORT', 5000))

config = Config()
