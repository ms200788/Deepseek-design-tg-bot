import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiohttp
from aiohttp import web
import json

from config import config
from database import db
from utils import BotUtils, FileHandler, Validation

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# States for conversation handlers
class UploadStates(StatesGroup):
    waiting_for_files = State()
    waiting_for_options = State()

class MessageStates(StatesGroup):
    waiting_for_start_text = State()
    waiting_for_help_text = State()

class BroadcastStates(StatesGroup):
    waiting_for_broadcast = State()

# Middleware to track user activity
@dp.middleware()
async def user_activity_middleware(handler, event, data):
    if hasattr(event, 'from_user') and event.from_user:
        user_id = event.from_user.id
        await db.update_user_activity(user_id)
    return await handler(event, data)

# Start command handler
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()
    
    # Add user to database
    await db.add_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    # Handle deep link access
    if args:
        await handle_deep_link_access(message, args)
        return
    
    # Normal start command
    message_data = await db.get_message('start_message')
    
    if message_data and message_data['image_id']:
        await message.answer_photo(
            photo=message_data['image_id'],
            caption=message_data['text'],
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Help", callback_data="help_button")
            )
        )
    else:
        await message.answer(
            text=message_data['text'] if message_data else "Welcome!",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Help", callback_data="help_button")
            )
        )

# Help command handler
@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    message_data = await db.get_message('help_message')
    
    if message_data and message_data['image_id']:
        await message.answer_photo(
            photo=message_data['image_id'],
            caption=message_data['text']
        )
    else:
        await message.answer(
            text=message_data['text'] if message_data else "Help information"
        )

# Help button callback
@dp.callback_query_handler(lambda c: c.data == 'help_button')
async def help_button_callback(callback_query: types.CallbackQuery):
    message_data = await db.get_message('help_message')
    
    if message_data and message_data['image_id']:
        await callback_query.message.answer_photo(
            photo=message_data['image_id'],
            caption=message_data['text']
        )
    else:
        await callback_query.message.answer(
            text=message_data['text'] if message_data else "Help information"
        )
    
    await callback_query.answer()

# Set image command (Owner only)
@dp.message_handler(commands=['setimage'], is_owner=True)
async def cmd_setimage(message: types.Message):
    if message.reply_to_message and (message.reply_to_message.photo or message.reply_to_message.document):
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("Start Image", callback_data="set_start_image"),
            InlineKeyboardButton("Help Image", callback_data="set_help_image")
        )
        await message.answer("Set as start image or help image?", reply_markup=keyboard)
    else:
        await message.answer("Please reply to an image with /setimage")

# Set image callback
@dp.callback_query_handler(lambda c: c.data.startswith('set_'), is_owner=True)
async def set_image_callback(callback_query: types.CallbackQuery):
    message = callback_query.message.reply_to_message
    file_id, file_type = FileHandler.get_file_id(message)
    
    if file_id:
        if callback_query.data == 'set_start_image':
            # Get current message to preserve text
            current_msg = await db.get_message('start_message')
            await db.set_message('start_message', current_msg['text'] if current_msg else None, file_id)
            await callback_query.message.edit_text("✅ Start image updated!")
        else:
            current_msg = await db.get_message('help_message')
            await db.set_message('help_message', current_msg['text'] if current_msg else None, file_id)
            await callback_query.message.edit_text("✅ Help image updated!")
    else:
        await callback_query.message.edit_text("❌ Error: Could not get file ID")
    
    await callback_query.answer()

# Set message command (Owner only)
@dp.message_handler(commands=['setmessage'], is_owner=True)
async def cmd_setmessage(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Start Message", callback_data="set_start_text"),
        InlineKeyboardButton("Help Message", callback_data="set_help_text")
    )
    await message.answer("Which message do you want to set?", reply_markup=keyboard)

# Set message callback
@dp.callback_query_handler(lambda c: c.data.startswith('set_'), is_owner=True)
async def set_message_callback(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == 'set_start_text':
        await MessageStates.waiting_for_start_text.set()
        await callback_query.message.answer("Please send the new start message text:")
    else:
        await MessageStates.waiting_for_help_text.set()
        await callback_query.message.answer("Please send the new help message text:")
    
    await callback_query.answer()

# Handle message text input
@dp.message_handler(state=MessageStates.waiting_for_start_text)
async def process_start_text(message: types.Message, state: FSMContext):
    # Get current image to preserve it
    current_msg = await db.get_message('start_message')
    await db.set_message('start_message', message.text, current_msg['image_id'] if current_msg else None)
    await message.answer("✅ Start message updated!")
    await state.finish()

@dp.message_handler(state=MessageStates.waiting_for_help_text)
async def process_help_text(message: types.Message, state: FSMContext):
    current_msg = await db.get_message('help_message')
    await db.set_message('help_message', message.text, current_msg['image_id'] if current_msg else None)
    await message.answer("✅ Help message updated!")
    await state.finish()

# Stats command (Owner only)
@dp.message_handler(commands=['stats'], is_owner=True)
async def cmd_stats(message: types.Message):
    await db.update_statistics()
    stats = await db.get_statistics()
    active_users = await db.get_active_users_count(48)
    
    stats_text = f"""
📊 **Bot Statistics**

👥 Total Users: `{stats['total_users']}`
✅ Active Users (48h): `{active_users}`
📁 Total Upload Sessions: `{stats['total_sessions']}`
📄 Total Files Uploaded: `{stats['total_uploads']}`
🕒 Last Updated: `{stats['last_updated'].strftime('%Y-%m-%d %H:%M')}`
    """
    
    await message.answer(stats_text)

# Broadcast command (Owner only)
@dp.message_handler(commands=['broadcast'], is_owner=True)
async def cmd_broadcast(message: types.Message, state: FSMContext):
    await BroadcastStates.waiting_for_broadcast.set()
    await message.answer("Please send the broadcast message (text, photo, video, or document):")

# Handle broadcast message
@dp.message_handler(state=BroadcastStates.waiting_for_broadcast, content_types=types.ContentType.ANY)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = await db.get_all_users()
    success_count = 0
    fail_count = 0
    
    await message.answer(f"📢 Starting broadcast to {len(users)} users...")
    
    for user in users:
        try:
            if message.photo:
                await bot.send_photo(
                    chat_id=user['id'],
                    photo=message.photo[-1].file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_markup=message.reply_markup
                )
            elif message.video:
                await bot.send_video(
                    chat_id=user['id'],
                    video=message.video.file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_markup=message.reply_markup
                )
            elif message.document:
                await bot.send_document(
                    chat_id=user['id'],
                    document=message.document.file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_markup=message.reply_markup
                )
            else:
                await bot.send_message(
                    chat_id=user['id'],
                    text=message.text,
                    entities=message.entities,
                    reply_markup=message.reply_markup
                )
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user['id']}: {e}")
            fail_count += 1
        
        await asyncio.sleep(0.1)
    
    await message.answer(f"""
📊 Broadcast Completed:
✅ Success: {success_count}
❌ Failed: {fail_count}
📊 Total: {len(users)}
    """)
    
    await state.finish()

# Upload command (Owner only)
@dp.message_handler(commands=['upload'], is_owner=True)
async def cmd_upload(message: types.Message, state: FSMContext):
    await state.update_data(
        file_ids=[],
        captions=[],
        file_types=[],
        messages_to_delete=[]
    )
    
    await UploadStates.waiting_for_files.set()
    await message.answer("""
📁 **Upload Session Started**

Please send files (photos, videos, documents):
- Send multiple files one by one
- Use `/d` when done
- Use `/c` to cancel

Supported formats: Images, Videos, Documents, Audio
    """)

# Handle file uploads
@dp.message_handler(state=UploadStates.waiting_for_files, content_types=types.ContentType.ANY)
async def process_file_upload(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        if message.text == '/d':
            await process_upload_complete(message, state)
            return
        elif message.text == '/c':
            await state.finish()
            await message.answer("❌ Upload session cancelled.")
            return
    
    file_id, file_type = FileHandler.get_file_id(message)
    
    if file_id and file_type != 'unknown':
        async with state.proxy() as data:
            data['file_ids'].append(file_id)
            data['file_types'].append(file_type)
            data['captions'].append(message.caption or "")
            data['messages_to_delete'].append(message.message_id)
        
        if config.UPLOAD_CHANNEL_ID:
            try:
                await message.forward(config.UPLOAD_CHANNEL_ID)
            except Exception as e:
                logger.error(f"Failed to forward to upload channel: {e}")
        
        await message.answer(f"✅ {file_type.capitalize()} added! ({len(data['file_ids'])} files)")
    else:
        await message.answer("❌ Unsupported file type. Please send photos, videos, or documents.")

async def process_upload_complete(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_ids = data.get('file_ids', [])
    
    if not file_ids:
        await message.answer("❌ No files uploaded. Session cancelled.")
        await state.finish()
        return
    
    await UploadStates.waiting_for_options.set()
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Protect Content", callback_data="protect_yes"),
        InlineKeyboardButton("❌ Don't Protect", callback_data="protect_no")
    )
    
    await message.answer(f"""
📊 Upload Summary:
📄 Files: {len(file_ids)}
📁 Types: {', '.join(set(data['file_types']))}

🔒 **Protect Content?**
Prevents forwarding/saving for users
    """, reply_markup=keyboard)

# Protect content callback
@dp.callback_query_handler(lambda c: c.data.startswith('protect_'), state=UploadStates.waiting_for_options)
async def protect_content_callback(callback_query: types.CallbackQuery, state: FSMContext):
    protect_content = callback_query.data == 'protect_yes'
    
    await state.update_data(protect_content=protect_content)
    
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.row(
        InlineKeyboardButton("5 min", callback_data="delete_5"),
        InlineKeyboardButton("1 hour", callback_data="delete_60"),
        InlineKeyboardButton("1 day", callback_data="delete_1440")
    )
    keyboard.row(
        InlineKeyboardButton("1 week", callback_data="delete_10080"),
        InlineKeyboardButton("Never", callback_data="delete_0")
    )
    
    await callback_query.message.edit_text(f"""
🔒 Content Protection: {'✅ ON' if protect_content else '❌ OFF'}

⏰ **Auto-delete Timer?**
Files will be automatically deleted from user's chat after specified time
    """, reply_markup=keyboard)
    
    await callback_query.answer()

# Auto-delete callback
@dp.callback_query_handler(lambda c: c.data.startswith('delete_'), state=UploadStates.waiting_for_options)
async def auto_delete_callback(callback_query: types.CallbackQuery, state: FSMContext):
    auto_delete_minutes = int(callback_query.data.split('_')[1])
    data = await state.get_data()
    
    # Generate random session ID
    session_id = BotUtils.generate_session_id()
    
    await db.create_upload_session(
        session_id=session_id,
        owner_id=callback_query.from_user.id,
        file_ids=data['file_ids'],
        captions=data['captions'],
        protect_content=data.get('protect_content', True),
        auto_delete_minutes=auto_delete_minutes
    )
    
    # Generate deep link with random session ID
    bot_username = (await bot.me).username
    deep_link = f"https://t.me/{bot_username}?start={session_id}"
    
    summary_text = f"""
🎉 **Upload Session Created!**

📊 Summary:
• Files: {len(data['file_ids'])}
• Protect Content: {'✅ Yes' if data.get('protect_content', True) else '❌ No'}
• Auto-delete: {BotUtils.format_time(auto_delete_minutes)}

🔗 **Deep Link:**
`{deep_link}`

📋 Share this link with users to access the files.
    """
    
    await callback_query.message.answer(summary_text)
    await state.finish()
    await callback_query.answer()

# Deep link access handler
async def handle_deep_link_access(message: types.Message, session_id: str):
    session = await db.get_upload_session(session_id)
    
    if not session:
        await message.answer("❌ Invalid or expired session link.")
        return
    
    user_id = message.from_user.id
    is_owner = Validation.is_owner(user_id)
    
    file_ids = json.loads(session['file_ids'])
    captions = json.loads(session['captions'])
    
    await message.answer(f"📁 Downloading {len(file_ids)} file(s)...")
    
    sent_messages = []
    for i, file_id in enumerate(file_ids):
        try:
            caption = captions[i] if i < len(captions) else ""
            protect_content = session['protect_content'] and not is_owner
            
            # Try different file types
            try:
                msg = await message.answer_document(
                    document=file_id,
                    caption=caption,
                    protect_content=protect_content
                )
                sent_messages.append(msg.message_id)
            except:
                try:
                    msg = await message.answer_photo(
                        photo=file_id,
                        caption=caption,
                        protect_content=protect_content
                    )
                    sent_messages.append(msg.message_id)
                except:
                    try:
                        msg = await message.answer_video(
                            video=file_id,
                            caption=caption,
                            protect_content=protect_content
                        )
                        sent_messages.append(msg.message_id)
                    except:
                        await message.answer(f"❌ Error sending file {i+1}")
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error sending file {i}: {e}")
            await message.answer(f"❌ Error sending file {i+1}")
    
    # Handle auto-delete for non-owners
    if not is_owner and session['auto_delete_minutes'] > 0:
        delete_notice = f"\n\n⚠️ These files will be automatically deleted in {BotUtils.format_time(session['auto_delete_minutes'])}."
        await message.answer(delete_notice)
        
        # Schedule deletion
        asyncio.create_task(
            delete_files_after_delay(message.chat.id, sent_messages, session['auto_delete_minutes'])
        )

async def delete_files_after_delay(chat_id: int, message_ids: list, delay_minutes: int):
    """Delete files after specified delay"""
    await asyncio.sleep(delay_minutes * 60)
    
    try:
        for msg_id in message_ids:
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception as e:
                logger.error(f"Error deleting message {msg_id}: {e}")
    except Exception as e:
        logger.error(f"Error in auto-delete: {e}")

# Error handler
@dp.errors_handler()
async def errors_handler(update, exception):
    logger.error(f"Update {update} caused error {exception}")
    return True

# Health check endpoint
async def health_check(request):
    return web.Response(text="ok")

# Webhook handler
async def webhook_handler(request):
    if request.method == "POST":
        update = types.Update(**await request.json())
        await dp.process_update(update)
    return web.Response()

# Initialize application
async def on_startup(app):
    await db.init()
    await db.update_statistics()
    
    if config.WEBHOOK_HOST:
        await bot.set_webhook(config.WEBHOOK_URL)
        logger.info(f"Webhook set to {config.WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await dp.storage.close()
    await bot.session.close()

# Create aiohttp web application
def create_web_app():
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_post(config.WEBHOOK_PATH, webhook_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

# Main function
if __name__ == '__main__':
    if config.WEBHOOK_HOST:
        web_app = create_web_app()
        web.run_app(
            web_app,
            host=config.WEBAPP_HOST,
            port=config.WEBAPP_PORT
        )
    else:
        executor.start_polling(dp, skip_updates=True)
