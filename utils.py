import random
import string
from datetime import datetime
import asyncio

class BotUtils:
    @staticmethod
    def generate_session_id(length: int = 12) -> str:
        """Generate random session ID with letters and digits"""
        characters = string.ascii_letters + string.digits
        return ''.join(random.choices(characters, k=length))

    @staticmethod
    def format_time(minutes: int) -> str:
        """Format minutes into human readable time"""
        if minutes == 0:
            return "never"
        
        if minutes < 60:
            return f"{minutes} minutes"
        elif minutes < 1440:
            hours = minutes // 60
            return f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            days = minutes // 1440
            return f"{days} day{'s' if days > 1 else ''}"

class FileHandler:
    @staticmethod
    def get_file_id(message):
        """Get file ID and file type from message"""
        if message.photo:
            return message.photo[-1].file_id, 'photo'
        elif message.video:
            return message.video.file_id, 'video'
        elif message.document:
            return message.document.file_id, 'document'
        elif message.audio:
            return message.audio.file_id, 'audio'
        else:
            return None, 'unknown'

class Validation:
    @staticmethod
    def is_owner(user_id: int) -> bool:
        from config import config
        return user_id == config.OWNER_ID
