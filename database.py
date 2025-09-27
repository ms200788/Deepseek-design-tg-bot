import asyncpg
from datetime import datetime
import json
from config import config

class Database:
    def __init__(self):
        self.pool = None

    async def init(self):
        self.pool = await asyncpg.create_pool(config.DATABASE_URL)
        await self.create_tables()

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    join_date TIMESTAMP DEFAULT NOW(),
                    last_active TIMESTAMP DEFAULT NOW(),
                    is_banned BOOLEAN DEFAULT FALSE
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    message_type VARCHAR(50) UNIQUE,
                    text TEXT,
                    image_id VARCHAR(500),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS upload_sessions (
                    session_id VARCHAR(100) PRIMARY KEY,
                    owner_id BIGINT,
                    file_ids JSONB,
                    captions JSONB,
                    protect_content BOOLEAN DEFAULT TRUE,
                    auto_delete_minutes INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    access_count INTEGER DEFAULT 0
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS statistics (
                    id SERIAL PRIMARY KEY,
                    total_users INTEGER DEFAULT 0,
                    total_uploads INTEGER DEFAULT 0,
                    total_sessions INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await self.initialize_default_messages(conn)

    async def initialize_default_messages(self, conn):
        default_messages = [
            ('start_message', '👋 Welcome to File Sharing Bot!\n\nUse /help to learn how to use this bot.', None),
            ('help_message', '📖 **Help Guide**\n\n• Use deep links to access files\n• Contact owner for support', None)
        ]
        
        for msg_type, text, image_id in default_messages:
            await conn.execute('''
                INSERT INTO messages (message_type, text, image_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (message_type) DO NOTHING
            ''', msg_type, text, image_id)

    async def add_user(self, user_id: int, username: str, first_name: str, last_name: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (id, username, first_name, last_name, join_date, last_active)
                VALUES ($1, $2, $3, $4, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                last_active = NOW()
            ''', user_id, username, first_name, last_name)

    async def update_user_activity(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE users SET last_active = NOW() WHERE id = $1
            ''', user_id)

    async def get_all_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch('SELECT * FROM users WHERE is_banned = FALSE')

    async def get_active_users_count(self, hours: int = 48):
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                SELECT COUNT(*) FROM users 
                WHERE last_active > NOW() - INTERVAL '1 hour' * $1 
                AND is_banned = FALSE
            ''', hours)

    async def set_message(self, message_type: str, text: str, image_id: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO messages (message_type, text, image_id, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (message_type) DO UPDATE SET
                text = EXCLUDED.text,
                image_id = EXCLUDED.image_id,
                updated_at = NOW()
            ''', message_type, text, image_id)

    async def get_message(self, message_type: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM messages WHERE message_type = $1', message_type)

    async def create_upload_session(self, session_id: str, owner_id: int, file_ids: list, 
                                  captions: list, protect_content: bool, auto_delete_minutes: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO upload_sessions 
                (session_id, owner_id, file_ids, captions, protect_content, auto_delete_minutes)
                VALUES ($1, $2, $3, $4, $5, $6)
            ''', session_id, owner_id, json.dumps(file_ids), json.dumps(captions), 
               protect_content, auto_delete_minutes)

    async def get_upload_session(self, session_id: str):
        async with self.pool.acquire() as conn:
            session = await conn.fetchrow('SELECT * FROM upload_sessions WHERE session_id = $1', session_id)
            if session:
                await conn.execute('''
                    UPDATE upload_sessions SET access_count = access_count + 1 WHERE session_id = $1
                ''', session_id)
            return session

    async def update_statistics(self):
        async with self.pool.acquire() as conn:
            total_users = await conn.fetchval('SELECT COUNT(*) FROM users WHERE is_banned = FALSE')
            total_sessions = await conn.fetchval('SELECT COUNT(*) FROM upload_sessions')
            total_uploads = await conn.fetchval('SELECT SUM(jsonb_array_length(file_ids)) FROM upload_sessions')
            
            await conn.execute('''
                INSERT INTO statistics (total_users, total_uploads, total_sessions, last_updated)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (id) DO UPDATE SET
                total_users = EXCLUDED.total_users,
                total_uploads = EXCLUDED.total_uploads,
                total_sessions = EXCLUDED.total_sessions,
                last_updated = NOW()
            ''', total_users, total_uploads, total_sessions)

    async def get_statistics(self):
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow('SELECT * FROM statistics ORDER BY last_updated DESC LIMIT 1')
            if not stats:
                await self.update_statistics()
                return await conn.fetchrow('SELECT * FROM statistics ORDER BY last_updated DESC LIMIT 1')
            return stats

db = Database()
