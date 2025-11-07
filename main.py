import os
import asyncio
from telethon import TelegramClient, events
from instagrapi import Client as InstaClient
from instagrapi.exceptions import ChallengeRequired, TwoFactorRequired, BadCredentials
from dotenv import load_dotenv
from flask import Flask
import threading

basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '.env')
load_dotenv(dotenv_path, override=True)

api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')
REQUIRED_CHANNEL = "devil_devo"
INSTA_PAGE_LINK = "https://www.instagram.com/phenoartgallery"

app = Flask(__name__)
client = TelegramClient('bot_session', api_id, api_hash)

# Memory
user_states = {}
user_credentials = {}
active_insta_sessions = {}
temp_insta_clients = {}
old_messages = {}
login_flow_messages = {}
user_bulk_photos = {}
user_2fa_data = {}

@app.route('/')
def health():
    return "Bot running!", 200

@app.route('/status')
def status():
    return f"Active users: {len(user_states)}", 200

async def delete_old_messages(user_id, event, skip_last=0, preserve_login=False):
    if user_id not in old_messages or not old_messages[user_id]:
        return
    messages_to_delete = old_messages[user_id][:-skip_last] if skip_last else old_messages[user_id]
    if preserve_login and user_id in login_flow_messages:
        messages_to_delete = [msg for msg in messages_to_delete if msg not in login_flow_messages[user_id]]
    for msg_id in messages_to_delete:
        try:
            await client.delete_messages(event.chat_id, msg_id)
        except:
            pass
    old_messages[user_id] = old_messages[user_id][-skip_last:] if skip_last else []

async def safe_reply(event, text, user_id, preserve=False):
    msg = await event.reply(text)
    if user_id not in old_messages:
        old_messages[user_id] = []
    old_messages[user_id].append(msg.id)
    if preserve:
        if user_id not in login_flow_messages:
            login_flow_messages[user_id] = []
        login_flow_messages[user_id].append(msg.id)
    return msg

async def is_channel_joined(user_id):
    try:
        channel = await client.get_entity(REQUIRED_CHANNEL)
        await client.get_permissions(channel, user_id)
        return True
    except:
        return False

def get_insta_client(user_id):
    if user_id in active_insta_sessions:
        return active_insta_sessions[user_id]
    if user_id in user_credentials:
        insta_username, insta_password = user_credentials[user_id]
        cl = InstaClient()
        try:
            cl.login(insta_username, insta_password)
            active_insta_sessions[user_id] = cl
            return cl
        except:
            return None
    return None

PRIVACY_POLICY = """
🔐 **PRIVACY & TERMS AGREEMENT**

**1️⃣ Your Responsibility:**
   • You are responsible for your Instagram username and password
   • Bot owner **DOES NOT** collect, store, or share credentials
   • Stored in RAM only (lost on restart)

**2️⃣ Data Security:**
   • Credentials **NEVER** saved to database
   • Bot accesses only for posting
   • **No personal data shared**

**3️⃣ Bot Disclaimer:**
   • Bot provided **"AS-IS"** without warranties
   • **NOT liable** for account issues
   • **Your responsibility**

**By using /agree:**
• Accept all terms above
• Take responsibility for security
• Acknowledge no data storage
"""

@client.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    user_id = event.sender_id
    sender = await event.get_sender()
    username = sender.username or sender.first_name or "User"

    if not await is_channel_joined(user_id):
        await safe_reply(event,
            f"👋 **Welcome, {username}!**\n\n"
            f"Join our channel first:\n"
            f"[Click to join](https://t.me/{REQUIRED_CHANNEL})\n\n"
            f"Use /start again after joining!",
            user_id)
        return

    if user_id in user_states and user_states[user_id] == 'verified':
        if user_id in user_credentials:
            insta_username, _ = user_credentials[user_id]
            await safe_reply(event,
                f"🎉 **Welcome back!**\n📸 Instagram: @{insta_username}\n🔐 Session: Active\n\n"
                f"Choose posting mode:\n/singlepost or /bulkpost",
                user_id)
        else:
            await safe_reply(event,
                "🎉 **Verified!**\nUse /login to connect Instagram.",
                user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return

    user_states[user_id] = 'awaiting_privacy'
    await safe_reply(event,
        f"✅ **Channel verified!**\n\n{PRIVACY_POLICY}\n\n**Type /agree to accept.**",
        user_id)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/agree'))
async def agree_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_states.get(user_id) == 'awaiting_privacy' and await is_channel_joined(user_id):
        user_states[user_id] = 'verified'
        await safe_reply(event, f"✅ **Verified!**\n\nUse /login to connect Instagram.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
    else:
        if user_id in user_states and user_states[user_id] == 'verified':
            return
        await safe_reply(event, "❌ Join channel and use /start first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/singlepost'))
async def singlepost_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_id not in user_credentials:
        await safe_reply(event, "❌ Instagram not connected. Use /login first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    user_states[user_id] = 'awaiting_single_photo'
    await safe_reply(event,
        "📸 **Single Post Mode**\n\nSend 1 photo with optional caption.\nBot will upload directly to Instagram.",
        user_id, preserve=True)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/bulkpost'))
async def bulkpost_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_id not in user_credentials:
        await safe_reply(event, "❌ Instagram not connected. Use /login first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    user_states[user_id] = 'awaiting_bulk_photo'
    user_bulk_photos[user_id] = []
    await safe_reply(event,
        "📸 **Bulk Post Mode (Carousel)**\n\nSend 1st image.\nAfter upload, you'll get options:\n/addmore - Add more images\n/postall - Post as carousel",
        user_id, preserve=True)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/addmore'))
async def addmore_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_states.get(user_id) != 'bulk_waiting_more':
        await safe_reply(event, "❌ Use /bulkpost first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    user_states[user_id] = 'awaiting_bulk_photo'
    await safe_reply(event,
        f"📸 **Image {len(user_bulk_photos[user_id]) + 1}**\n\nSend next image or:\n/addmore - Add one more\n/postall - Upload carousel",
        user_id, preserve=True)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/postall'))
async def postall_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_id not in user_bulk_photos or not user_bulk_photos[user_id]:
        await safe_reply(event, "❌ No images collected. Use /bulkpost.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    user_states[user_id] = 'awaiting_caption_choice'
    await safe_reply(event,
        f"📸 **{len(user_bulk_photos[user_id])} images ready!**\n\nChoose caption:\n/defaultcaption - Bot credit only\n/mycaption - Your custom caption",
        user_id, preserve=True)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/defaultcaption'))
async def defaultcaption_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_states.get(user_id) != 'awaiting_caption_choice':
        await safe_reply(event, "❌ Use /postall first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    caption = "🤖✨ Posted via TG bot: @insta_frwd_bot 🤖✨"
    await handle_bulk_upload(event, user_id, caption)

@client.on(events.NewMessage(pattern='/mycaption'))
async def mycaption_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_states.get(user_id) != 'awaiting_caption_choice':
        await safe_reply(event, "❌ Use /postall first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    user_states[user_id] = 'awaiting_custom_caption'
    await safe_reply(event,
        "📝 **Send your custom caption:**\n\n(Bot credit will be added automatically)",
        user_id, preserve=True)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/help'))
async def help_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    await safe_reply(event,
        "📚 **Bot Help**\n\n**Commands:**\n/start - Start\n/login - Connect Instagram\n/singlepost - Upload 1 image\n/bulkpost - Upload multiple images (carousel)\n/addmore - Add more images in bulk\n/postall - Post all images\n/account - View connected account\n/logout - Disconnect\n/help - Help",
        user_id)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/account'))
async def account_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_id not in user_credentials:
        await safe_reply(event, "❌ No Instagram connected.", user_id)
    else:
        insta_username, _ = user_credentials[user_id]
        status = "🟢 Active" if user_id in active_insta_sessions else "🟡 Ready"
        await safe_reply(event,
            f"✅ **Connected:** @{insta_username}\n🔐 **Status:** {status}\n\nUse /singlepost or /bulkpost",
            user_id)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(pattern='/logout'))
async def logout_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_id in user_credentials:
        insta_username, _ = user_credentials[user_id]
        user_credentials.pop(user_id, None)
        active_insta_sessions.pop(user_id, None)
        user_states[user_id] = 'verified'
        user_bulk_photos.pop(user_id, None)
        await safe_reply(event,
            f"✅ **Disconnected:** @{insta_username}\n\nUse /login to reconnect.",
            user_id)
    else:
        await safe_reply(event, "❌ No account connected", user_id)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=False)

@client.on(events.NewMessage(pattern='/login'))
async def login_command(event):
    user_id = event.sender_id
    try:
        await client.delete_messages(event.chat_id, event.id)
    except:
        pass
    
    if user_id in user_credentials:
        insta_username, _ = user_credentials[user_id]
        await safe_reply(event,
            f"✅ **Already connected**\n📸 @{insta_username}\n\nUse /logout first to connect different account.",
            user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        return
    
    if user_states.get(user_id) == 'verified':
        user_states[user_id] = 'awaiting_insta_username'
        await safe_reply(event,
            "📱 **Setup Instagram**\n\nStep 1️⃣: Send username (without @)",
            user_id, preserve=True)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
    else:
        await safe_reply(event, "❌ Use /start and /agree first.", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)

@client.on(events.NewMessage(incoming=True, forwards=False))
async def handle_all_messages(event):
    user_id = event.sender_id
    msg = event.message
    
    if msg.photo and user_id in user_credentials:
        if user_states.get(user_id) == 'awaiting_single_photo':
            await handle_single_upload(event, user_id)
            user_states[user_id] = 'verified'
            return
        
        if user_states.get(user_id) == 'awaiting_bulk_photo':
            try:
                image_path = await msg.download_media(file=f'bulk_{user_id}_{len(user_bulk_photos[user_id])}.jpg')
                user_bulk_photos[user_id].append(image_path)
                photo_count = len(user_bulk_photos[user_id])
                
                await safe_reply(event,
                    f"📸 **Image {photo_count} collected!**\n\n/addmore - Add more images\n/postall - Upload as carousel",
                    user_id, preserve=True)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                user_states[user_id] = 'bulk_waiting_more'
                return
            except Exception as e:
                await safe_reply(event, f"❌ Error: {str(e)}", user_id)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                return
    
    if msg.text:
        text = msg.raw_text.strip().lower()
        if text.startswith('/'):
            return
        
        if user_states.get(user_id) == 'awaiting_custom_caption':
            custom_caption = event.raw_text.strip()
            caption = f"{custom_caption}\n\n🤖✨ Posted via TG bot: @insta_frwd_bot 🤖✨"
            await handle_bulk_upload(event, user_id, caption)
            return
        
        if user_states.get(user_id) == 'awaiting_insta_username':
            insta_username = text
            if ' ' in insta_username or '@' in insta_username:
                await safe_reply(event, "❌ Invalid username", user_id)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                return
            user_states[user_id] = 'awaiting_insta_password'
            user_states[f"{user_id}_username"] = insta_username
            await safe_reply(event, 
                f"✅ Username: **{insta_username}**\n\nStep 2️⃣: Send password",
                user_id, preserve=True)
            await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
            return
        
        if user_states.get(user_id) == 'awaiting_insta_password':
            insta_username = user_states.get(f"{user_id}_username")
            insta_password = str(text)
            
            await safe_reply(event, "🔐 Verifying... (may take 10-15 seconds)", user_id)
            await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
            
            try:
                cl = InstaClient()
                cl.login(insta_username, insta_password)
                
                user_credentials[user_id] = (insta_username, insta_password)
                active_insta_sessions[user_id] = cl
                user_states[user_id] = 'verified'
                user_states.pop(f"{user_id}_username", None)
                
                await safe_reply(event,
                    f"✅ **Connected!**\n📸 @{insta_username}\n\nChoose:\n/singlepost or /bulkpost",
                    user_id)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=False)
                print(f"✅ Login success: {insta_username}")
                
            except BadCredentials:
                await safe_reply(event,
                    f"❌ **Wrong credentials for {insta_username}**\n\nUse /login to retry",
                    user_id)
                user_states.pop(f"{user_id}_username", None)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                
            except ChallengeRequired as e:
                user_states[user_id] = 'awaiting_2fa_code'
                user_2fa_data[user_id] = {
                    'username': insta_username,
                    'password': insta_password,
                    'client': cl
                }
                
                await safe_reply(event,
                    f"🚨 **2FA Required for {insta_username}**\n\n"
                    f"Instagram sent a code.\n"
                    f"Send the 6-digit code here.",
                    user_id, preserve=True)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                print(f"⚠️ 2FA required: {insta_username}")
                
            except TwoFactorRequired:
                user_states[user_id] = 'awaiting_2fa_code'
                user_2fa_data[user_id] = {
                    'username': insta_username,
                    'password': insta_password,
                    'client': cl
                }
                
                await safe_reply(event,
                    f"🚨 **2FA Required for {insta_username}**\n\n"
                    f"Open your authenticator app.\n"
                    f"Send the 6-digit code here.",
                    user_id, preserve=True)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                
            except Exception as e:
                error_msg = str(e).lower()
                if 'please wait' in error_msg or 'rate limit' in error_msg:
                    await safe_reply(event,
                        f"⏳ **Instagram Rate Limited**\n\n"
                        f"Please wait 30-60 minutes before trying again.",
                        user_id)
                else:
                    await safe_reply(event,
                        f"❌ **Login Failed:** {str(e)}\n\nUse /login to retry",
                        user_id)
                user_states.pop(f"{user_id}_username", None)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                print(f"❌ Login error: {str(e)}")
            return
        
        if user_states.get(user_id) == 'awaiting_2fa_code':
            otp = text.strip()
            if not otp.isdigit() or len(otp) != 6:
                await safe_reply(event, "❌ Invalid code. Send 6-digit code", user_id)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                return
            
            await safe_reply(event, "🔐 Verifying code...", user_id)
            await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
            
            if user_id not in user_2fa_data:
                await safe_reply(event, "❌ Session expired. Use /login again.", user_id)
                user_states.pop(user_id, None)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                return
            
            try:
                insta_username = user_2fa_data[user_id]['username']
                insta_password = user_2fa_data[user_id]['password']
                
                cl = InstaClient()
                cl.login(insta_username, insta_password, verification_code=otp)
                
                user_credentials[user_id] = (insta_username, insta_password)
                active_insta_sessions[user_id] = cl
                user_states[user_id] = 'verified'
                user_2fa_data.pop(user_id, None)
                
                await safe_reply(event,
                    f"✅ **Verified!**\n📸 @{insta_username}\n\n"
                    f"Choose:\n/singlepost or /bulkpost",
                    user_id)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=False)
                print(f"✅ 2FA success: {insta_username}")
                
            except Exception as e:
                user_2fa_data.pop(user_id, None)
                user_states.pop(user_id, None)
                await safe_reply(event,
                    f"❌ **Code invalid:** {str(e)}\n\nUse /login to retry",
                    user_id)
                await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
                print(f"❌ 2FA failed: {str(e)}")

async def handle_single_upload(event, user_id):
    insta_username, insta_password = user_credentials[user_id]
    user_caption = event.raw_text or ""
    caption = f"{user_caption}\n\n🤖✨ Posted via TG bot: @insta_frwd_bot 🤖✨" if user_caption else f"🤖✨ Posted via TG bot: @insta_frwd_bot 🤖✨"
    image_path = None
    
    await safe_reply(event, "📥 Downloading...", user_id)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
    
    try:
        image_path = await event.message.download_media(file='temp_image.jpg')
        cl = get_insta_client(user_id)
        if not cl:
            cl = InstaClient()
            cl.login(insta_username, insta_password)
            active_insta_sessions[user_id] = cl
        
        await safe_reply(event, "📤 Uploading...", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        
        media = cl.photo_upload(image_path, caption)
        link = f"https://www.instagram.com/p/{media.code}/"
        
        await safe_reply(event,
            f"✅ **Posted!**\n{INSTA_PAGE_LINK}\n\n"
            f"📸 @{insta_username}\n📝 {user_caption[:50]}{'...' if len(user_caption) > 50 else ''}\n"
            f"🔗 {link}\n\n🔐 Use /singlepost or /bulkpost",
            user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        print(f"✅ Single posted")
        
    except Exception as e:
        active_insta_sessions.pop(user_id, None)
        await safe_reply(event, f"❌ **Error:** {str(e)}", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

async def handle_bulk_upload(event, user_id, caption):
    if user_id not in user_bulk_photos or not user_bulk_photos[user_id]:
        return
    
    insta_username, insta_password = user_credentials[user_id]
    image_paths = user_bulk_photos[user_id]
    
    await safe_reply(event, f"📤 Uploading {len(image_paths)} images...", user_id)
    await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
    
    try:
        cl = get_insta_client(user_id)
        if not cl:
            cl = InstaClient()
            cl.login(insta_username, insta_password)
            active_insta_sessions[user_id] = cl
        
        media = cl.album_upload(image_paths, caption=caption)
        link = f"https://www.instagram.com/p/{media.code}/"
        
        await safe_reply(event,
            f"✅ **Carousel Posted!**\n{INSTA_PAGE_LINK}\n\n"
            f"📸 @{insta_username}\n🖼️ {len(image_paths)} images\n"
            f"🔗 {link}\n\n🔐 Use /singlepost or /bulkpost",
            user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
        print(f"✅ Carousel posted")
        
    except Exception as e:
        active_insta_sessions.pop(user_id, None)
        await safe_reply(event, f"❌ **Error:** {str(e)}", user_id)
        await delete_old_messages(user_id, event, skip_last=1, preserve_login=True)
    finally:
        for path in image_paths:
            if path and os.path.exists(path):
                os.remove(path)
        user_bulk_photos.pop(user_id, None)

# ✅ Worker async start - 100% correct for Railway

async def run_bot():
    await client.start(bot_token=bot_token)
    print("✓ Telegram bot connected!")
    await client.run_until_disconnected()

def start_bot_sync():
    asyncio.run(run_bot())

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_bot_sync, daemon=False)
    bot_thread.start()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
