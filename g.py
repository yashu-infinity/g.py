# ============================================================
# YASHU STORE BOT – FINAL PRODUCTION READY
# ✅ UNIQUE PAYABLE AMOUNT (3 DECIMALS, 0.001–0.499 OFFSET)
# ✅ UNIQUENESS CHECK AGAINST PENDING ORDERS
# ✅ TIMER EXPIRY CANCELLED ON SUCCESS
# ✅ ALL FEATURES INTACT
# ============================================================

import os
import sqlite3
import asyncio
import logging
import time
import re
import random
import string
import json
import requests
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from io import BytesIO
from collections import defaultdict

# ---------- QR LIBRARIES ----------
try:
    import qrcode
    from PIL import Image
    QR_LIBS_OK = True
except ImportError:
    qrcode = None
    Image = None
    QR_LIBS_OK = False

# -----------------------------------------------
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
try:
    from telegram import CopyTextButton
    COPY_TEXT_SUPPORTED = True
except ImportError:
    CopyTextButton = None
    COPY_TEXT_SUPPORTED = False

from telegram.error import (
    BadRequest,
    NetworkError,
    TimedOut,
    RetryAfter,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# SETTINGS (🔴 इन्हें अपने हिसाब से बदलें)
# ============================================================
BOT_TOKEN = "8975679008:AAH3X-LbHcnPLQj1TWhP6lRRiDoCX8aCuMU"   # YOUR BOT TOKEN
ADMIN_CHAT_ID = 8827266713                                   # YOUR ADMIN ID
SUPPORT = os.getenv("SUPPORT_USERNAME", "@Yashucarromofficial").strip()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- DATABASE ----
DB = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "yashu_store.db")).strip()
if not DB:
    DB = os.path.join(BASE_DIR, "yashu_store.db")

# ===== FAMAPI =====
FAMAPI_BASE_URL = os.getenv("FAMAPI_BASE_URL", "https://py.freepanel.in/api/v1")
FAMAPI_API_KEY = os.getenv("FAMAPI_API_KEY", "FAM_LIVE_sk_A9FZXGd8B2j611TgIj4l5MSRwqmBi4Ux").strip()
FAMAPI_REDIRECT_URL = os.getenv("FAMAPI_REDIRECT_URL", f"https://t.me/{BOT_TOKEN.split(':')[0]}")

# ===== LOCAL UPI (fallback) =====
MY_FAMPAY_ID = "vishwa150608@fam"

# ===== DEFAULT WELCOME VIDEO =====
DEFAULT_WELCOME_VIDEO = "BAACAgUAAxkBAAFTO6Zqlrzi4YmUwXvpbZw3fGITgjG1tgACzSEAAhyFsFSP5J5GmO0Gwz0E"

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("YASHU_STORE")

# ============================================================
# DATABASE
# ============================================================
@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def setup_db():
    with db() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance REAL DEFAULT 0,
                role TEXT DEFAULT 'user',
                blocked INTEGER DEFAULT 0,
                created_at TEXT DEFAULT '',
                bonus_claimed INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                duration TEXT NOT NULL,
                price REAL DEFAULT 0,
                UNIQUE(name, duration)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reseller_prices (
                reseller_id INTEGER,
                product_id INTEGER,
                price REAL,
                PRIMARY KEY(reseller_id, product_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                license_key TEXT UNIQUE,
                status TEXT DEFAULT 'available',
                sold_to INTEGER,
                sold_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                amount REAL,
                payable_amount REAL,
                screenshot TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                product_id INTEGER,
                license_key TEXT,
                price REAL,
                purchased_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auto_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                order_id TEXT UNIQUE,
                amount REAL,
                payable_amount REAL,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                updated_at TEXT,
                qr_message_ids TEXT,
                verify_attempts INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS processed_payments (
                order_id TEXT PRIMARY KEY,
                processed_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Enable auto-verify by default (but will be used with unique amounts)
        cur.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('auto_verify', '1')")
        cur.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('welcome_video', ?)", (DEFAULT_WELCOME_VIDEO,))

        # ---- Ensure all columns exist ----
        cur.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cur.fetchall()}
        required = {
            "username": "TEXT DEFAULT ''",
            "first_name": "TEXT DEFAULT ''",
            "balance": "REAL DEFAULT 0",
            "role": "TEXT DEFAULT 'user'",
            "blocked": "INTEGER DEFAULT 0",
            "created_at": "TEXT DEFAULT ''",
            "bonus_claimed": "INTEGER DEFAULT 0",
        }
        for col, defn in required.items():
            if col not in columns:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")

        cur.execute("PRAGMA table_info(products)")
        prod_cols = {row[1] for row in cur.fetchall()}
        if "price_bronze" not in prod_cols:
            cur.execute("ALTER TABLE products ADD COLUMN price_bronze REAL DEFAULT 0")

        cur.execute("PRAGMA table_info(auto_payments)")
        auto_cols = {row[1] for row in cur.fetchall()}
        if "payable_amount" not in auto_cols:
            cur.execute("ALTER TABLE auto_payments ADD COLUMN payable_amount REAL")
        if "qr_message_ids" not in auto_cols:
            cur.execute("ALTER TABLE auto_payments ADD COLUMN qr_message_ids TEXT")
        if "verify_attempts" not in auto_cols:
            cur.execute("ALTER TABLE auto_payments ADD COLUMN verify_attempts INTEGER DEFAULT 0")

        # ---- Insert default products ----
        products = [
            ("KOS", "1 Day", 100),
            ("KOS", "7 Days", 280),
            ("KOS", "15 Days", 450),
            ("KOS", "30 Days", 820),
            ("SNAKE", "3 Days", 200),
            ("SNAKE", "10 Days", 500),
            ("SNAKE", "30 Days", 950),
            ("AIM AI", "1 Day", 100),
            ("AIM AI", "3 Days", 250),
            ("AIM AI", "7 Days", 500),
            ("AIM AI", "15 Days", 900),
            ("AIM AI", "30 Days", 1500),
        ]
        for name, duration, price in products:
            cur.execute("INSERT OR IGNORE INTO products (name, duration, price) VALUES (?, ?, ?)", (name, duration, price))

        # ---- Ensure admin exists ----
        cur.execute("""
            INSERT OR IGNORE INTO users (chat_id, username, first_name, balance, role, blocked, created_at, bonus_claimed)
            VALUES (?, ?, ?, 0, 'admin', 0, ?, 0)
        """, (ADMIN_CHAT_ID, "ADMIN", "YASHU ADMIN", datetime.now().isoformat()))
        cur.execute("UPDATE users SET role='admin', blocked=0 WHERE chat_id=?", (ADMIN_CHAT_ID,))

# ============================================================
# HELPERS
# ============================================================
def now():
    return datetime.now().isoformat()

def money(value):
    """Display amount with 2 decimals (for normal prices)."""
    try:
        rounded = round(float(value), 2)
        if abs(rounded) < 0.001:
            return "0"
        return f"{rounded:.2f}".rstrip('0').rstrip('.')
    except:
        return "0"

def format_payable(value):
    """Display payable amount with 3 decimal places (for uniqueness)."""
    try:
        rounded = round(float(value), 3)
        if abs(rounded) < 0.0001:
            return "0"
        return f"{rounded:.3f}".rstrip('0').rstrip('.')
    except:
        return "0"

def get_setting(key):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

def set_setting(key, value):
    with db() as con:
        cur = con.cursor()
        cur.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))

def register_user(user):
    if not user:
        return
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("INSERT OR IGNORE INTO users (chat_id, username, first_name, created_at) VALUES (?, ?, ?, ?)",
                        (user.id, user.username or "", user.first_name or "", now()))
            cur.execute("UPDATE users SET username=?, first_name=? WHERE chat_id=?", (user.username or "", user.first_name or "", user.id))
    except Exception as e:
        logger.error(f"register_user: {e}")

def get_user(uid):
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT chat_id, username, first_name, balance, role, blocked, created_at, bonus_claimed FROM users WHERE chat_id=?", (uid,))
            return cur.fetchone()
    except:
        return None

def is_admin(uid):
    return int(uid) == ADMIN_CHAT_ID

def is_reseller(uid):
    row = get_user(uid)
    return row and row[4] == "reseller"

def is_blocked(uid):
    row = get_user(uid)
    return row and row[5] == 1

def get_price(uid, product_id):
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT price, price_bronze FROM products WHERE id=?", (product_id,))
            row = cur.fetchone()
            if not row:
                return 0
            normal_price, reseller_price = row
            if not is_reseller(uid):
                return float(normal_price)
            cur.execute("SELECT price FROM reseller_prices WHERE reseller_id=? AND product_id=?", (uid, product_id))
            custom = cur.fetchone()
            if custom:
                return float(custom[0])
            return float(reseller_price) if reseller_price > 0 else float(normal_price)
    except:
        return 0

def safe_float(value):
    try:
        return float(value)
    except:
        return None

def get_user_display(uid):
    row = get_user(uid)
    if not row:
        return "Unknown", "", f"User {uid}"
    first = row[2] or "User"
    username = row[1] or ""
    display = f"{first} (@{username})" if username else first
    return first, username, display

# ============================================================
# RATE LIMITING
# ============================================================
_rate_limiter = defaultdict(list)
_RATE_LIMIT_CLEANUP_INTERVAL = 300

async def rate_limit_cleanup():
    while True:
        await asyncio.sleep(_RATE_LIMIT_CLEANUP_INTERVAL)
        now_t = time.time()
        for uid in list(_rate_limiter.keys()):
            _rate_limiter[uid] = [t for t in _rate_limiter[uid] if now_t - t < 1]
            if not _rate_limiter[uid]:
                del _rate_limiter[uid]

def rate_limit(uid, max_calls=3, period=1):
    now_t = time.time()
    _rate_limiter[uid] = [t for t in _rate_limiter[uid] if now_t - t < period]
    if len(_rate_limiter[uid]) >= max_calls:
        return False
    _rate_limiter[uid].append(now_t)
    return True

# ============================================================
# BROADCAST FUNCTIONS
# ============================================================
async def broadcast_message(bot, users, text, exclude=None, semaphore=None):
    if semaphore is None:
        semaphore = asyncio.Semaphore(20)
    async def send_one(uid):
        if uid == exclude:
            return False
        async with semaphore:
            try:
                await bot.send_message(chat_id=uid, text=text)
                return True
            except:
                return False
    tasks = [send_one(uid) for uid in users]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    sent = sum(1 for r in results if r is True)
    return sent

async def broadcast_photo(bot, users, photo_data, caption="", exclude=None, semaphore=None):
    if semaphore is None:
        semaphore = asyncio.Semaphore(20)
    photo_data.seek(0)
    photo_bytes = photo_data.read()
    async def send_one(uid):
        if uid == exclude:
            return False
        async with semaphore:
            try:
                bio = BytesIO(photo_bytes)
                await bot.send_photo(chat_id=uid, photo=bio, caption=caption)
                return True
            except:
                return False
    tasks = [send_one(uid) for uid in users]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return sum(1 for r in results if r is True)

async def broadcast_key_purchase(bot, buyer_id, game_name, engine_name, plan, amount, order_id, stock_remaining, purchase_time):
    try:
        dt_utc = datetime.fromisoformat(purchase_time)
        IST = timezone(timedelta(hours=5, minutes=30))
        dt_ist = dt_utc.replace(tzinfo=timezone.utc).astimezone(IST)
        time_str = dt_ist.strftime("%d/%m/%Y, %I:%M:%S %p").lower()
    except:
        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)
        time_str = now_ist.strftime("%d/%m/%Y, %I:%M:%S %p").lower()
    broadcast_msg = (
        f"🛒 **NEW PURCHASE RECORDED**\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 Game: {game_name}\n"
        f"⚡ Engine: {engine_name}\n"
        f"⏳ Plan: {plan}\n"
        f"💰 Amount: ₹{money(amount)}\n\n"
        f"👤 Buyer ID: {buyer_id}\n\n"
        f"🧾 Order ID:\n{order_id}\n\n"
        f"📦 Stock Remaining: {stock_remaining}\n\n"
        f"✨ Another successful delivery completed\n"
        f"🕒 {time_str}"
    )
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT chat_id FROM users WHERE blocked=0")
        all_users = [row[0] for row in cur.fetchall()]
    sent = await broadcast_message(bot, all_users, broadcast_msg, exclude=buyer_id)
    logger.info(f"Key purchase broadcast sent to {sent} users (excluded buyer {buyer_id})")

# ============================================================
# TELEGRAM SAFE FUNCTIONS
# ============================================================
async def answer_callback(query, text=None, alert=False):
    try:
        await query.answer(text=text, show_alert=alert)
    except:
        pass

async def safe_edit(query, text, reply_markup=None):
    try:
        if not query.message:
            return
        if query.message.text is not None:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        elif query.message.caption is not None:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        else:
            await query.message.reply_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning("SAFE EDIT: %s", e)
            await query.message.reply_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.exception("SAFE EDIT: %r", e)
        try:
            await query.message.reply_text(text=text, reply_markup=reply_markup)
        except:
            pass

async def send_message_safe(bot, chat_id, text, reply_markup=None):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except RetryAfter as e:
        await asyncio.sleep(min(float(e.retry_after), 5))
        try:
            return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        except:
            return None
    except:
        return None

def copy_key_button(key):
    if COPY_TEXT_SUPPORTED:
        try:
            return InlineKeyboardButton("📋 COPY KEY", copy_text=CopyTextButton(text=str(key)))
        except:
            pass
    return InlineKeyboardButton("🔑 KEY SHOWN ABOVE", callback_data="copy_unavailable")

# ============================================================
# KEYBOARDS
# ============================================================
def main_menu(uid):
    buttons = [
        [InlineKeyboardButton("🛒 BUY ENGINE", callback_data="buy")],
        [InlineKeyboardButton("💰 ADD FUND", callback_data="fund"), InlineKeyboardButton("👤 ACCOUNT", callback_data="account")],
        [InlineKeyboardButton("📦 CHECK STOCK", callback_data="check_stock")],
        [InlineKeyboardButton("📜 HISTORY", callback_data="history"), InlineKeyboardButton("🏆 LEADERBOARD", callback_data="leaderboard")],
        [InlineKeyboardButton("📞 SUPPORT", callback_data="support")],
    ]
    if is_reseller(uid):
        buttons.append([InlineKeyboardButton("🤝 RESELLER PANEL", callback_data="reseller")])
    if is_admin(uid):
        buttons.append([InlineKeyboardButton("👑 ADMIN PANEL", callback_data="admin")])
    return InlineKeyboardMarkup(buttons)

def back_button(target="back"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data=target)]])

def admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 USERS & BALANCE", callback_data="users")],
        [InlineKeyboardButton("🔁 TOGGLE AUTO-VERIFY", callback_data="toggle_auto")],
        [InlineKeyboardButton("💰 WALLET MANAGER", callback_data="wallet")],
        [InlineKeyboardButton("💰 CHANGE NORMAL PRICE", callback_data="change_normal")],
        [InlineKeyboardButton("💎 SET GLOBAL RESELLER PRICE", callback_data="change_reseller")],
        [InlineKeyboardButton("💰 CUSTOM RESELLER PRICE", callback_data="reseller_price")],
        [InlineKeyboardButton("🤝 ADD RESELLER", callback_data="add_reseller"), InlineKeyboardButton("❌ REMOVE RESELLER", callback_data="remove_reseller")],
        [InlineKeyboardButton("📦 ADD STOCK", callback_data="add_stock")],
        [InlineKeyboardButton("📊 STOCK", callback_data="stock_list"), InlineKeyboardButton("📦 PRODUCTS", callback_data="products")],
        [InlineKeyboardButton("🗑 DELETE STOCK", callback_data="delete_stock")],
        [InlineKeyboardButton("💳 PENDING PAYMENTS", callback_data="pending")],
        [InlineKeyboardButton("📢 ANNOUNCEMENT", callback_data="announcement")],
        [InlineKeyboardButton("💬 MESSAGE USER", callback_data="message")],
        [InlineKeyboardButton("📊 STATISTICS", callback_data="stats")],
        [InlineKeyboardButton("🚫 BLOCK / UNBLOCK", callback_data="block")],
        [InlineKeyboardButton("🎥 WELCOME VIDEO", callback_data="change_welcome_video")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ])

# ============================================================
# ASYNC NETWORK HELPERS
# ============================================================
def _sync_post(url, headers, data, timeout=15):
    return requests.post(url, headers=headers, json=data, timeout=timeout)

def _sync_get(url, headers=None, timeout=15):
    return requests.get(url, headers=headers, timeout=timeout)

# ============================================================
# FAMAPI FUNCTIONS
# ============================================================
async def create_famapi_order(amount_rupees, chat_id, user_name="User", bot=None):
    try:
        url = f"{FAMAPI_BASE_URL}/orders"
        headers = {
            "Authorization": f"Bearer {FAMAPI_API_KEY}",
            "Content-Type": "application/json"
        }
        amount_paise = int(round(amount_rupees * 100))
        payload = {
            "amount": amount_paise,
            "receipt": f"ORDER_{chat_id}_{int(time.time())}",
            "redirect_url": FAMAPI_REDIRECT_URL
        }
        logger.info(f"FamAPI REQUEST: {url} | payload: {payload}")
        print(f"[DEBUG] FamAPI REQUEST: {url} | payload: {payload}")

        response = await asyncio.to_thread(_sync_post, url, headers, payload, 30)
        logger.info(f"FamAPI response status: {response.status_code}")
        logger.info(f"FamAPI response text: {response.text[:500]}")
        print(f"[DEBUG] FamAPI response status: {response.status_code}")
        print(f"[DEBUG] FamAPI response text: {response.text[:500]}")

        if response.status_code not in (200, 201):
            error_text = response.text[:500]
            if bot:
                await send_message_safe(bot, ADMIN_CHAT_ID,
                    f"❌ FamAPI Order Creation Failed\n"
                    f"Status: {response.status_code}\n"
                    f"Response: {error_text}\n\n"
                    f"🔑 API Key: {FAMAPI_API_KEY[:10]}...\n"
                    f"🌐 Base URL: {FAMAPI_BASE_URL}\n"
                    f"🔗 Redirect: {FAMAPI_REDIRECT_URL}\n\n"
                    f"Check your API key, base URL, and internet connection.")
            return None

        data = response.json()
        if "id" in data:
            return {
                "order_id": data["id"],
                "payment_link": data.get("payment_link", ""),
                "qr_url": data.get("qr_url", ""),
                "payable_amount": amount_rupees
            }
        else:
            logger.error(f"Unexpected response: {data}")
            if bot:
                await send_message_safe(bot, ADMIN_CHAT_ID,
                    f"❌ FamAPI unexpected response: {data}")
            return None
    except Exception as e:
        logger.exception("FamAPI create order error")
        if bot:
            await send_message_safe(bot, ADMIN_CHAT_ID,
                f"❌ Create Order Exception: {str(e)}\n\nCheck your network & API key.")
        return None

async def verify_famapi_order(order_id):
    try:
        url = f"{FAMAPI_BASE_URL}/verify/{order_id}"
        headers = {
            "Authorization": f"Bearer {FAMAPI_API_KEY}",
            "Content-Type": "application/json"
        }
        response = await asyncio.to_thread(_sync_get, url, headers, 60)
        logger.info(f"FamAPI verify {order_id}: {response.status_code} - {response.text[:200]}")
        print(f"[DEBUG] FamAPI verify {order_id}: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            return None
    except Exception as e:
        logger.exception("FamAPI verify error")
        return None

async def delete_qr_messages(bot, chat_id, order_id):
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT qr_message_ids FROM auto_payments WHERE order_id=?", (order_id,))
            row = cur.fetchone()
            if not row or not row[0]:
                return
            msg_ids = json.loads(row[0])
            for msg_id in msg_ids:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except:
                    pass
    except Exception as e:
        logger.warning(f"Failed to delete QR messages for {order_id}: {e}")

# ============================================================
# BACKGROUND VERIFICATION TASK
# ============================================================
async def background_verifier(bot):
    while True:
        try:
            with db() as con:
                cur = con.cursor()
                cur.execute("""
                    SELECT order_id, chat_id, payable_amount, verify_attempts
                    FROM auto_payments
                    WHERE status='pending' AND datetime(created_at) <= datetime('now', '-10 seconds')
                """)
                pending = cur.fetchall()

            for order_id, chat_id, payable_amount, attempts in pending:
                with db() as con2:
                    cur2 = con2.cursor()
                    cur2.execute("SELECT 1 FROM processed_payments WHERE order_id=?", (order_id,))
                    if cur2.fetchone():
                        continue

                result = await verify_famapi_order(order_id)
                if not result:
                    with db() as con3:
                        cur3 = con3.cursor()
                        cur3.execute("UPDATE auto_payments SET verify_attempts = verify_attempts + 1 WHERE order_id=?", (order_id,))
                    continue

                status = result.get("status")
                if status == "success":
                    data = result.get("data", {})
                    transaction_id = data.get("transaction_id", "N/A")
                    utr = data.get("utr", "N/A")

                    with db() as con4:
                        cur4 = con4.cursor()
                        cur4.execute("SELECT balance FROM users WHERE chat_id=?", (chat_id,))
                        old_balance = cur4.fetchone()[0]

                        cur4.execute("UPDATE auto_payments SET status='success', updated_at=? WHERE order_id=? AND status='pending'", 
                                    (now(), order_id))
                        if cur4.rowcount == 0:
                            continue
                        cur4.execute("SELECT payable_amount FROM auto_payments WHERE order_id=?", (order_id,))
                        payable_row = cur4.fetchone()
                        if not payable_row:
                            continue
                        payable = payable_row[0]

                        cur4.execute("UPDATE users SET balance = balance + ? WHERE chat_id=?", (payable, chat_id))
                        cur4.execute("SELECT balance FROM users WHERE chat_id=?", (chat_id,))
                        new_balance = cur4.fetchone()[0]

                        cur4.execute("INSERT INTO processed_payments (order_id, processed_at) VALUES (?, ?)", 
                                    (order_id, now()))

                    await delete_qr_messages(bot, chat_id, order_id)

                    await send_message_safe(bot, chat_id,
                        f"✅ PAYMENT RECEIVED!\n\n"
                        f"💰 ₹{money(payable)} added.\n"
                        f"💳 New Balance: ₹{money(new_balance)}\n"
                        f"🆔 Txn ID: `{transaction_id}`"
                    )

                    first, username, display = get_user_display(chat_id)
                    await send_message_safe(bot, ADMIN_CHAT_ID,
                        f"✅ **PAYMENT RECEIVED**\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 {display} [`{chat_id}`]\n"
                        f"📛 @{username if username else 'N/A'}\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Previous Balance: ₹{money(old_balance)}\n"
                        f"➕ Added Balance: ₹{money(payable)}\n"
                        f"💳 New Balance: ₹{money(new_balance)}\n"
                        f"🆔 Txn ID: `{transaction_id}`\n"
                        f"📌 UTR: `{utr}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🆔 Order: {order_id}")
                elif status == "pending":
                    with db() as con5:
                        cur5 = con5.cursor()
                        cur5.execute("UPDATE auto_payments SET verify_attempts = verify_attempts + 1 WHERE order_id=?", (order_id,))

                with db() as con6:
                    cur6 = con6.cursor()
                    cur6.execute("SELECT verify_attempts, created_at FROM auto_payments WHERE order_id=?", (order_id,))
                    row = cur6.fetchone()
                    if row:
                        attempts2 = row[0]
                        created = datetime.fromisoformat(row[1])
                        if attempts2 >= 3 or (datetime.now() - created).total_seconds() > 3600:
                            cur6.execute("UPDATE auto_payments SET status='expired' WHERE order_id=?", (order_id,))
                            await send_message_safe(bot, chat_id,
                                "❌ Payment verification failed / expired.\n"
                                "Please contact support if you have paid, or try again with a new fund request.")
        except Exception as e:
            logger.exception("Background verifier error")
        await asyncio.sleep(30)

# ============================================================
# BUY ENGINE
# ============================================================
async def show_buy(query):
    await safe_edit(query,
        "🛒 BUY ENGINE\n\nSelect engine:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 KOS", callback_data="engine_KOS")],
            [InlineKeyboardButton("🐍 SNAKE", callback_data="engine_SNAKE")],
            [InlineKeyboardButton("🤖 AIM AI", callback_data="engine_AIM AI")],
            [InlineKeyboardButton("🔙 BACK", callback_data="back")]
        ]))

async def show_engine(query, engine):
    if engine == "KOS":
        await safe_edit(query,
            "🎯 KOS - Select Game:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🎮 CARROM", callback_data="game_KOS_CARROM")],
                [InlineKeyboardButton("🔙 BACK", callback_data="buy")]
            ]))
        return
    await show_plans(query, query.from_user.id, engine)

async def show_plans(query, uid, engine):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT id, duration FROM products WHERE name=? ORDER BY id", (engine,))
        rows = cur.fetchall()
    buttons = []
    for pid, duration in rows:
        price = get_price(uid, pid)
        buttons.append([InlineKeyboardButton(f"⚡ {duration} • ₹{money(price)}", callback_data=f"plan_{pid}")])
    buttons.append([InlineKeyboardButton("🔙 BACK", callback_data="buy")])
    await safe_edit(query, f"🔥 {engine} ENGINE\n\nSelect plan:", InlineKeyboardMarkup(buttons))

async def buy_key(query, context, pid):
    uid = query.from_user.id
    if is_blocked(uid):
        await safe_edit(query, "🚫 Blocked.")
        return
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT id, name, duration FROM products WHERE id=?", (pid,))
            product = cur.fetchone()
            if not product:
                await safe_edit(query, "❌ Product not found.", back_button("buy"))
                return
            price = get_price(uid, pid)
            cur.execute("SELECT balance FROM users WHERE chat_id=?", (uid,))
            balance = cur.fetchone()[0]
            if balance < price:
                await safe_edit(query, f"❌ Insufficient balance\nPrice: ₹{money(price)}\nBalance: ₹{money(balance)}", back_button())
                return
            cur.execute("SELECT id, license_key FROM stock WHERE product_id=? AND status='available' LIMIT 1", (pid,))
            stock = cur.fetchone()
            if not stock:
                await safe_edit(query, "❌ OUT OF STOCK", back_button())
                return
            stock_id, license_key = stock

            cur.execute("UPDATE users SET balance = balance - ? WHERE chat_id = ?", (price, uid))
            cur.execute("SELECT balance FROM users WHERE chat_id=?", (uid,))
            new_balance = cur.fetchone()[0]
            if new_balance < 0:
                con.rollback()
                await safe_edit(query, "❌ Insufficient balance (concurrency issue).", back_button())
                return

            cur.execute("UPDATE stock SET status='sold', sold_to=?, sold_at=? WHERE id=? AND status='available'", (uid, now(), stock_id))
            if cur.rowcount != 1:
                con.rollback()
                await safe_edit(query, "❌ Stock just sold.", back_button())
                return

            purchase_time = now()
            cur.execute("INSERT INTO purchases (chat_id, product_id, license_key, price, purchased_at) VALUES (?, ?, ?, ?, ?)",
                        (uid, pid, license_key, price, purchase_time))
            purchase_id = cur.lastrowid

            cur.execute("SELECT COUNT(*) FROM stock WHERE product_id=? AND status='available'", (pid,))
            stock_count = cur.fetchone()[0]

            user = query.from_user
            first_name = user.first_name or "User"
            username = user.username or ""
            engine_name = product[1]
            duration = product[2]
            game_name = "Carrom" if engine_name == "KOS" else engine_name

            first, username, display = get_user_display(uid)
            await send_message_safe(context.bot, ADMIN_CHAT_ID,
                f"🛒 **New Purchase**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Name: {first}\n"
                f"🆔 Chat ID: {uid}\n"
                f"📛 Username: @{username if username else 'N/A'}\n"
                f"🎮 Game: {game_name}\n"
                f"⚡ Engine: {engine_name}\n"
                f"📅 Day: {duration}\n"
                f"📦 Stock Available: {stock_count}\n"
                f"━━━━━━━━━━━━━━━━━━━━")

            await broadcast_key_purchase(
                context.bot,
                uid,
                game_name,
                engine_name,
                duration,
                price,
                f"YASHU-{int(time.time())}",
                stock_count,
                purchase_time
            )

            await safe_edit(query,
                f"✅ PURCHASE SUCCESSFUL!\n\n"
                f"🎯 {product[1]}\n"
                f"⚡ {product[2]}\n"
                f"💰 Paid: ₹{money(price)}\n"
                f"💳 Balance: ₹{money(new_balance)}\n\n"
                f"🔑 KEY:\n`{license_key}`\n\n"
                f"Tap the button below to copy the key.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 COPY KEY", callback_data=f"copy_key_{purchase_id}")],
                    [InlineKeyboardButton("📜 HISTORY", callback_data="history"), InlineKeyboardButton("🏠 HOME", callback_data="back")]
                ]))
    except Exception as e:
        logger.exception("BUY ERROR")
        await safe_edit(query, "❌ Purchase error.", back_button())

# ============================================================
# FUND (QR GENERATION) – WITH UNIQUE PAYABLE AMOUNT
# ============================================================
async def fund_menu(query, context):
    context.user_data.clear()
    order_id = f"YASHU-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
    context.user_data["state"] = "fund_amount"
    context.user_data["order_id"] = order_id
    context.user_data["order_expiry"] = time.time() + 300
    await safe_edit(query,
        "💰 ADD FUND\n\nEnter amount (₹1 minimum):\nExample: 500",
        back_button())

async def send_qr(update, amount, context):
    try:
        order_id = context.user_data.get("order_id", f"YASHU-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}")
        user = update.effective_user

        # ---- Generate unique payable amount ----
        # Max offset: 0.499 (3 decimal places)
        MAX_OFFSET = 0.499
        # Get existing pending orders with the same base amount
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT payable_amount FROM auto_payments WHERE amount=? AND status='pending'", (amount,))
            existing = [row[0] for row in cur.fetchall()]

        # Generate offset until unique
        attempts = 0
        while attempts < 50:  # safety limit
            offset = round(random.uniform(0.001, MAX_OFFSET), 3)
            payable = round(amount + offset, 3)
            if payable not in existing:
                break
            attempts += 1
        else:
            # Fallback: if still not unique, use exact amount (but this should rarely happen)
            payable = round(amount, 2)
            await update.message.reply_text("⚠️ Could not generate unique payable amount. Using exact amount.")

        auto_verify = get_setting("auto_verify") == "1" and bool(FAMAPI_API_KEY)
        fam_order_id = None
        display_txn_id = order_id

        if auto_verify:
            order_data = await create_famapi_order(payable, user.id, user.first_name or "User", bot=context.bot)
            if order_data:
                fam_order_id = order_data.get("order_id")
                payment_link = order_data.get("payment_link")
                if fam_order_id:
                    context.user_data["fam_order_id"] = fam_order_id
                    display_txn_id = fam_order_id
                    with db() as con:
                        cur = con.cursor()
                        cur.execute(
                            "INSERT INTO auto_payments (chat_id, order_id, amount, payable_amount, status, created_at) "
                            "VALUES (?, ?, ?, ?, 'pending', ?)",
                            (user.id, fam_order_id, payable, float(payable), now())
                        )
                upi_link = payment_link if payment_link else f"upi://pay?pa={MY_FAMPAY_ID}&am={payable}&cu=INR&tn=Payment%20for%20Order%20{order_id}"
            else:
                # Auto-verify fail → manual with exact amount
                auto_verify = False
                payable = round(amount, 2)
                await update.message.reply_text("⚠️ Auto-verify failed. Using manual screenshot method.")
                upi_id = MY_FAMPAY_ID
                fam_order_id = None
                upi_link = f"upi://pay?pa={upi_id}&am={payable}&cu=INR&tn=Payment%20for%20Order%20{order_id}"
        else:
            # Manual mode – exact amount
            payable = round(amount, 2)
            upi_id = MY_FAMPAY_ID
            fam_order_id = None
            upi_link = f"upi://pay?pa={upi_id}&am={payable}&cu=INR&tn=Payment%20for%20Order%20{order_id}"

        context.user_data["payable_amount"] = payable
        msg_ids = []

        try:
            if not QR_LIBS_OK or qrcode is None:
                raise RuntimeError("QR libraries missing. Install qrcode[pil].")
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(upi_link)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            bio = BytesIO()
            img.save(bio, format='PNG')
            bio.seek(0)

            payable_str = format_payable(payable)
            amount_str = format_payable(amount)  # to show with 2 decimals
            caption = (
                f"💳 SCAN & PAY\n\n"
                f"💰 Amount: ₹{money(amount)}\n"
                f"🔢 Payable: ₹{payable_str}\n"
                f"🆔 Order: `{order_id}`\n"
                f"🆔 Txn ID: `{display_txn_id}`\n"
                f"⏳ Expires in: 05:00\n\n"
                f"UPI ID: `{MY_FAMPAY_ID}`\n\n"
                f"⚠️ Pay exact payable amount for safety."
            )
            qr_msg = await update.message.reply_photo(photo=bio, caption=caption, parse_mode="Markdown")
            msg_ids.append(qr_msg.message_id)

            if auto_verify:
                info_text = (
                    "⏳ **Payment Instructions**\n\n"
                    "1. Scan the QR code and pay the **exact payable amount** shown above.\n"
                    "2. We will **automatically** verify your payment.\n\n"
                    f"✅ **Your Transaction ID:** `{display_txn_id}`\n"
                    "⏳ We will check your payment at regular intervals.\n"
                    "You will be notified when balance is added."
                )
            else:
                info_text = (
                    "⏳ **Payment Instructions**\n\n"
                    "1. Scan the QR code and pay the **exact payable amount**.\n"
                    "2. After payment, tap **SEND SCREENSHOT** to submit your proof."
                )
            info_msg = await update.message.reply_text(info_text)
            msg_ids.append(info_msg.message_id)

            timer_msg = await start_timer(update, context, order_id)
            msg_ids.append(timer_msg.message_id)

            if not auto_verify:
                btn_msg = await update.message.reply_text(
                    "✅ After payment, tap **SEND SCREENSHOT** to submit your proof.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📸 SEND SCREENSHOT", callback_data="send_screenshot")]
                    ])
                )
                msg_ids.append(btn_msg.message_id)

            if fam_order_id:
                with db() as con:
                    cur = con.cursor()
                    cur.execute(
                        "UPDATE auto_payments SET qr_message_ids = ? WHERE order_id = ?",
                        (json.dumps(msg_ids), fam_order_id)
                    )

            return True

        except Exception as qr_error:
            logger.exception("QR generation error")
            if context.bot:
                await send_message_safe(context.bot, ADMIN_CHAT_ID, f"❌ QR error: {str(qr_error)}")
            fallback_msg = await update.message.reply_text(
                f"⚠️ QR generation failed.\n\n"
                f"💰 Amount: ₹{money(amount)}\n"
                f"🔢 Payable: ₹{payable_str}\n"
                f"🆔 Order: `{order_id}`\n\n"
                f"Please manually send ₹{payable_str} to UPI: `{MY_FAMPAY_ID}`\n\n"
                "After payment, tap **SEND SCREENSHOT**.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📸 SEND SCREENSHOT", callback_data="send_screenshot")]
                ])
            )
            if fam_order_id:
                with db() as con:
                    cur = con.cursor()
                    cur.execute(
                        "UPDATE auto_payments SET qr_message_ids = ? WHERE order_id = ?",
                        (json.dumps([fallback_msg.message_id]), fam_order_id)
                    )
            return True

    except Exception as e:
        logger.exception("send_qr outer error")
        if context.bot:
            await send_message_safe(context.bot, ADMIN_CHAT_ID, f"❌ Outer QR error: {str(e)}")
        await update.message.reply_text("❌ Payment initiation failed.")
        return False

# ============================================================
# TIMER (FIXED – CHECKS ORDER STATUS BEFORE EXPIRY)
# ============================================================
async def start_timer(update, context, order_id):
    expiry_seconds = 300
    uid = update.effective_user.id
    timer_msg = await update.message.reply_text(
        f"⏳ Order expires in: 05:00\n\n🆔 {order_id}"
    )
    context.user_data["timer_msg_id"] = timer_msg.message_id

    async def update_timer():
        remaining = expiry_seconds
        while remaining > 0:
            await asyncio.sleep(5)
            remaining -= 5
            if remaining < 0:
                remaining = 0
            mins = remaining // 60
            secs = remaining % 60
            try:
                await timer_msg.edit_text(
                    f"⏳ Order expires in: {mins:02d}:{secs:02d}\n\n🆔 {order_id}"
                )
            except Exception:
                break

        # Check if order already successful
        try:
            with db() as con:
                cur = con.cursor()
                cur.execute("SELECT status FROM auto_payments WHERE order_id=?", (order_id,))
                row = cur.fetchone()
                if row and row[0] == "success":
                    return  # don't send expiry
        except:
            pass

        # Expiry message
        try:
            await timer_msg.edit_text(
                f"❌ Order Expired!\n\n🆔 {order_id}\n\nPlease Add Fund again."
            )
        except Exception:
            pass

        user = get_user(uid)
        if user:
            first_name = user[2] or "User"
            username = user[1] or "N/A"
            await send_message_safe(context.bot, ADMIN_CHAT_ID,
                f"⏳ **Payment Expired**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 Order: {order_id}\n"
                f"👤 User: {first_name}\n"
                f"📛 @{username}\n"
                f"🆔 Chat ID: {uid}\n"
                f"📌 The QR code expired without payment.")
    asyncio.create_task(update_timer())
    return timer_msg

# ============================================================
# PAYMENT PHOTO (MANUAL APPROVAL)
# ============================================================
async def photo_handler(update, context):
    user = update.effective_user
    if not user or not update.message:
        return
    register_user(user)
    uid = user.id
    if is_blocked(uid):
        return
    
    if context.user_data.get("admin_state") == "announcement":
        if not is_admin(uid):
            return
        photo = update.message.photo[-1]
        caption = update.message.caption or ""
        photo_file = await photo.get_file()
        bio = BytesIO()
        await photo_file.download_to_memory(bio)
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT chat_id FROM users WHERE blocked=0")
            users = [row[0] for row in cur.fetchall()]
        sent = await broadcast_photo(context.bot, users, bio, caption)
        await update.message.reply_text(f"✅ Photo Announcement sent to {sent} users.")
        context.user_data.pop("admin_state", None)
        return

    if context.user_data.get("state") != "waiting_photo":
        await update.message.reply_text("📸 I wasn't expecting a photo. Use /start to go to main menu.")
        return
    amount = safe_float(context.user_data.get("amount"))
    if amount is None:
        context.user_data.clear()
        await update.message.reply_text("❌ Invalid payment amount.")
        return
    if not update.message.photo:
        return
    photo = update.message.photo[-1]
    payable = context.user_data.get("payable_amount", amount)
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO payments (chat_id, amount, payable_amount, screenshot, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
            """, (uid, amount, payable, photo.file_id, now()))
            payment_id = cur.lastrowid
    except sqlite3.Error as e:
        logger.exception("PAYMENT SAVE: %r", e)
        await update.message.reply_text("❌ Payment save failed. Please try again.")
        return
    context.user_data.clear()
    await update.message.reply_text("📸 Screenshot received! Waiting for admin approval.")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_{payment_id}"),
            InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{payment_id}")
        ],
        [InlineKeyboardButton("📋 VIEW", callback_data=f"payment_{payment_id}")]
    ])
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo.file_id,
            caption=(
                "💳 NEW PAYMENT\n\n"
                f"🆔 #{payment_id}\n"
                f"👤 User: {uid}\n"
                f"💰 Amount: ₹{money(amount)}\n"
                f"🔢 Payable: ₹{money(payable)}\n"
                "📌 PENDING"
            ),
            reply_markup=keyboard
        )
    except Exception as e:
        logger.exception("ADMIN PAYMENT SEND: %r", e)

# ============================================================
# ACCOUNT / HISTORY / LEADERBOARD
# ============================================================
async def account_page(query):
    uid = query.from_user.id
    user = get_user(uid)
    if not user:
        await safe_edit(query, "❌ User not found.", back_button())
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM purchases WHERE chat_id=?", (uid,))
        count, lifetime = cur.fetchone()
    role = user[4]
    tier_text = "Reseller" if role == "reseller" else "User"
    await safe_edit(query,
        f"👤 ACCOUNT\n\n🆔 {user[0]}\n👤 {user[2] or 'User'}\n📛 @{user[1] or 'N/A'}\n💰 ₹{money(user[3])}\n💎 Lifetime: ₹{money(lifetime)}\n🛒 Purchases: {count}\n👑 Role: {role.upper()}\n🏷️ {tier_text}",
        back_button())

async def history_page(query):
    uid = query.from_user.id
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT p.name, p.duration, pu.license_key, pu.price, pu.purchased_at FROM purchases pu JOIN products p ON p.id=pu.product_id WHERE pu.chat_id=? ORDER BY pu.id DESC LIMIT 10", (uid,))
        rows = cur.fetchall()
    if not rows:
        await safe_edit(query, "📜 No purchases yet.", back_button())
        return
    text = "📜 HISTORY\n\n"
    for row in rows:
        text += f"🎯 {row[0]}\n⚡ {row[1]}\n🔑 {row[2]}\n💰 ₹{money(row[3])}\n🕐 {row[4][:19]}\n━━━━━\n"
    await safe_edit(query, text, back_button())

async def leaderboard_page(query):
    with db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT users.chat_id, users.username, users.first_name, COALESCE(SUM(purchases.price), 0) as total
            FROM users
            LEFT JOIN purchases ON users.chat_id = purchases.chat_id
            GROUP BY users.chat_id
            ORDER BY total DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
    if not rows or rows[0][3] == 0:
        await safe_edit(query, "🏆 LEADERBOARD\n\nNo purchases yet. Be the first to buy!", back_button())
        return
    text = "🏆 LEADERBOARD - Top Buyers\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, row in enumerate(rows):
        chat_id, username, first_name, total = row
        name = first_name or username or str(chat_id)
        text += f"{medals[i]} {name[:20]} – ₹{money(total)}\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━\n"
    text += "🎁 ₹200 BONUS for the Top Buyer each month!\n"
    text += "Winner will be announced on the 1st of every month.\n"
    text += "Keep buying to climb the ranks!"
    await safe_edit(query, text, back_button())

# ============================================================
# ADMIN USERS
# ============================================================
async def admin_users(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT chat_id, username, first_name, balance, role, blocked FROM users ORDER BY chat_id DESC LIMIT 50")
        rows = cur.fetchall()
    buttons = []
    for row in rows:
        status = "🚫" if row[5] else "🟢"
        name = row[2] or row[1] or str(row[0])
        buttons.append([InlineKeyboardButton(f"{status} {name[:18]} • ₹{money(row[3])}", callback_data=f"user_{row[0]}")])
    buttons.append([InlineKeyboardButton("🔙 ADMIN", callback_data="admin")])
    await safe_edit(query, "👥 USERS", InlineKeyboardMarkup(buttons))

async def admin_user_details(query, target):
    if not is_admin(query.from_user.id):
        return
    user = get_user(target)
    if not user:
        await safe_edit(query, "❌ User not found.", back_button("users"))
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM purchases WHERE chat_id=?", (target,))
        count, spent = cur.fetchone()
    role = user[4]
    tier_text = "Reseller" if role == "reseller" else "User"
    await safe_edit(query,
        f"👤 USER DETAILS\n\n🆔 {user[0]}\n👤 {user[2] or 'N/A'}\n📛 @{user[1] or 'N/A'}\n💰 ₹{money(user[3])}\n👑 Role: {user[4]}\n🏷️ {tier_text}\n🚫 Blocked: {'YES' if user[5] else 'NO'}\n🛒 Purchases: {count}\n💎 Spent: ₹{money(spent)}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 ADD BALANCE", callback_data=f"useradd_{target}"), InlineKeyboardButton("💵 REMOVE", callback_data=f"userremove_{target}")],
            [InlineKeyboardButton("💵 SET BALANCE", callback_data=f"userset_{target}")],
            [InlineKeyboardButton("🚫 BLOCK", callback_data=f"userblock_{target}"), InlineKeyboardButton("🟢 UNBLOCK", callback_data=f"userunblock_{target}")],
            [InlineKeyboardButton("🔙 USERS", callback_data="users")]
        ]))

# ============================================================
# ADMIN PAGES
# ============================================================
async def wallet_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "wallet"
    await safe_edit(query,
        "💰 WALLET MANAGER\n\nFormat:\nCHAT_ID +500\nCHAT_ID -100\n\nExample:\n123456789 +500",
        back_button("admin"))

async def add_reseller_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "add_reseller_simple"
    await safe_edit(query,
        "🤝 ADD RESELLER\n\nSend **Chat ID** of the user to promote:\n\n(No tier needed)",
        back_button("admin"))

async def remove_reseller_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "remove_reseller"
    await safe_edit(query, "❌ REMOVE RESELLER\n\nSend Chat ID:", back_button("admin"))

async def reseller_price_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "reseller_price"
    await safe_edit(query,
        "💰 CUSTOM RESELLER PRICE\n\n"
        "Set a custom price for a specific reseller and product.\n"
        "Format:\n`RESELLER_ID PRODUCT_ID PRICE`\n\n"
        "Example:\n`123456789 1 80`\n\n"
        "(This overrides the global reseller price)",
        back_button("admin"))

async def block_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "block"
    await safe_edit(query,
        "🚫 BLOCK / UNBLOCK\n\nFormat:\nCHAT_ID block\nCHAT_ID unblock\n\nExample:\n123456789 block",
        back_button("admin"))

async def message_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "message"
    await safe_edit(query,
        "💬 MESSAGE USER\n\nFormat:\nCHAT_ID MESSAGE\n\nExample:\n123456789 Hello",
        back_button("admin"))

async def announcement_page(query, context):
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    context.user_data["admin_state"] = "announcement"
    await safe_edit(query,
        "📢 ANNOUNCEMENT\n\nSend a **text** message or **photo** (with optional caption).\nIt will be broadcast to all users.",
        back_button("admin"))

async def reseller_list_page(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT u.chat_id, u.username, u.first_name, IFNULL(SUM(p.price), 0) as total_spend
            FROM users u
            LEFT JOIN purchases p ON u.chat_id = p.chat_id
            WHERE u.role = 'reseller'
            GROUP BY u.chat_id
            ORDER BY total_spend DESC
        """)
        resellers = cur.fetchall()
    if not resellers:
        await safe_edit(query, "❌ No resellers found.", reply_markup=back_button("admin"))
        return
    msg = "👥 **RESELLER LIST**\n━━━━━━━━━━━━━━━━━━━\n\n"
    for chat_id, username, first_name, spend in resellers:
        display_name = f"@{username}" if username else (first_name or "Unknown")
        msg += f"  • `{chat_id}` | {display_name} | ₹{money(spend)}\n"
    msg += "\n💡 *Total Spend = Lifetime purchases*"
    if len(msg) > 4000:
        msg = msg[:3900] + "\n... (truncated)"
    await safe_edit(query, msg, reply_markup=back_button("admin"))

# ============================================================
# STOCK
# ============================================================
async def stock_engine_page(query, engine):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT id, duration FROM products WHERE name=? ORDER BY id", (engine,))
        rows = cur.fetchall()
    buttons = []
    for pid, duration in rows:
        buttons.append([InlineKeyboardButton(f"⚡ {duration}", callback_data=f"stockpid_{pid}")])
    buttons.append([InlineKeyboardButton("🔙 BACK", callback_data="add_stock")])
    await safe_edit(query, f"📦 {engine} STOCK\nSelect duration:", InlineKeyboardMarkup(buttons))

async def stock_product_page(query, context, pid):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT name, duration FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        if not product:
            await safe_edit(query, "❌ Product not found.", back_button("add_stock"))
            return
    context.user_data.clear()
    context.user_data["admin_state"] = "stock_keys"
    context.user_data["stock_product_id"] = pid
    await safe_edit(query,
        f"📦 ADD STOCK\n\n🎯 {product[0]}\n⚡ {product[1]}\n\nPaste keys (one per line):",
        back_button("add_stock"))

async def add_stock_text(update, context):
    pid = context.user_data.get("stock_product_id")
    if pid is None:
        await update.message.reply_text("❌ Session expired. Go to Add Stock again.")
        context.user_data.clear()
        return
    raw_keys = update.message.text.splitlines()
    keys = [k.strip() for k in raw_keys if k.strip()]
    if not keys:
        await update.message.reply_text("❌ No keys found.")
        return
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT name, duration FROM products WHERE id=?", (pid,))
            product = cur.fetchone()
            if not product:
                await update.message.reply_text("❌ Product not found.")
                context.user_data.clear()
                return
            added = 0
            duplicate = 0
            for key in keys:
                try:
                    cur.execute("INSERT INTO stock (product_id, license_key, status) VALUES (?, ?, 'available')", (pid, key))
                    added += 1
                except sqlite3.IntegrityError:
                    duplicate += 1
            context.user_data.clear()
            await update.message.reply_text(
                f"✅ STOCK ADDED\n\n🎯 {product[0]}\n⚡ {product[1]}\n\n✅ Added: {added}\n⚠️ Duplicate: {duplicate}",
                reply_markup=back_button("admin"))
    except Exception as e:
        logger.exception("ADD STOCK")
        await update.message.reply_text("❌ Stock database error.")

async def stock_list_page(query):
    if not is_admin(query.from_user.id):
        return
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT p.name, p.duration, COUNT(s.id)
                FROM products p LEFT JOIN stock s ON s.product_id=p.id AND s.status='available'
                GROUP BY p.id ORDER BY p.id
            """)
            rows = cur.fetchall()
        if not rows:
            await safe_edit(query, "📊 AVAILABLE STOCK\n\n✅ No stock.", back_button("admin"))
            return
        text = "📊 AVAILABLE STOCK\n\n"
        for row in rows:
            text += f"🎯 {row[0]}\n⚡ {row[1]}\n📦 Available: {row[2]}\n\n"
        await safe_edit(query, text, back_button("admin"))
    except Exception as e:
        logger.exception("STOCK LIST ERROR")
        await safe_edit(query, "❌ Error loading stock.", back_button("admin"))

async def delete_stock_page(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT id, name, duration FROM products ORDER BY id")
        rows = cur.fetchall()
    buttons = []
    for pid, name, duration in rows:
        buttons.append([InlineKeyboardButton(f"🗑 {name} • {duration}", callback_data=f"delstock_{pid}")])
    buttons.append([InlineKeyboardButton("🗑 DELETE ALL STOCK", callback_data="deleteallstock")])
    buttons.append([InlineKeyboardButton("🔙 ADMIN", callback_data="admin")])
    await safe_edit(query, "🗑 DELETE STOCK\nSelect plan:", InlineKeyboardMarkup(buttons))

async def delete_stock_product(query, pid):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT name, duration FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        if not product:
            await safe_edit(query, "❌ PRODUCT NOT FOUND.", back_button("delete_stock"))
            return
        cur.execute("SELECT COUNT(*) FROM stock WHERE product_id=? AND status='available'", (pid,))
        count = cur.fetchone()[0]
        cur.execute("DELETE FROM stock WHERE product_id=? AND status='available'", (pid,))
    await safe_edit(query,
        f"🗑 STOCK DELETED\n\n🎯 {product[0]}\n⚡ {product[1]}\n📦 Deleted: {count}",
        back_button("admin"))

async def delete_all_stock(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM stock WHERE status='available'")
        count = cur.fetchone()[0]
        cur.execute("DELETE FROM stock WHERE status='available'")
    await safe_edit(query,
        f"🗑 DELETE ALL STOCK\n\n✅ Deleted available keys: {count}\n\nSold history preserved.",
        back_button("admin"))

async def products_page(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT id, name, duration, price FROM products ORDER BY id")
        rows = cur.fetchall()
    if not rows:
        await safe_edit(query, "📦 PRODUCTS\n\nNo products.", back_button("admin"))
        return
    text = "📦 PRODUCTS\n\n"
    for row in rows:
        text += f"🆔 {row[0]}\n🎯 {row[1]}\n⚡ {row[2]}\n💰 {money(row[3])}\n━━━━━\n"
    await safe_edit(query, text, back_button("admin"))

async def stats_page(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT() FROM users")
        users = cur.fetchone()[0]
        cur.execute("SELECT COUNT() FROM users WHERE blocked=1")
        blocked = cur.fetchone()[0]
        cur.execute("SELECT COUNT() FROM users WHERE role='reseller'")
        resellers = cur.fetchone()[0]
        cur.execute("SELECT COUNT() FROM stock WHERE status='available'")
        avail = cur.fetchone()[0]
        cur.execute("SELECT COUNT() FROM stock WHERE status='sold'")
        sold = cur.fetchone()[0]
        cur.execute("SELECT COUNT() FROM purchases")
        purchases = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(price),0) FROM purchases")
        revenue = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(balance),0) FROM users")
        wallet_total = cur.fetchone()[0] or 0
    await safe_edit(query,
        f"📊 STATISTICS\n\n👥 Users: {users}\n🚫 Blocked: {blocked}\n🤝 Resellers: {resellers}\n\n📦 Available: {avail}\n📤 Sold: {sold}\n🛒 Purchases: {purchases}\n💰 Revenue: ₹{money(revenue)}\n💳 Wallets: ₹{money(wallet_total)}",
        back_button("admin"))

# ============================================================
# PENDING PAYMENTS
# ============================================================
async def pending_page(query):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT id, chat_id, amount FROM payments WHERE status='pending' ORDER BY id DESC LIMIT 50")
        rows = cur.fetchall()
    if not rows:
        await safe_edit(query, "💳 No pending payments.", back_button("admin"))
        return
    buttons = []
    for row in rows:
        buttons.append([InlineKeyboardButton(f"💳 #{row[0]} • ₹{money(row[2])}", callback_data=f"payment_{row[0]}")])
    buttons.append([InlineKeyboardButton("🔙 ADMIN", callback_data="admin")])
    await safe_edit(query, "💳 PENDING PAYMENTS", InlineKeyboardMarkup(buttons))

async def payment_view(query, context, payment_id):
    if not is_admin(query.from_user.id):
        return
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT chat_id, amount, screenshot, status, created_at FROM payments WHERE id=?", (payment_id,))
        payment = cur.fetchone()
    if not payment:
        await safe_edit(query, "❌ Payment not found.", back_button("pending"))
        return
    target, amount, screenshot, status, created = payment
    keyboard = []
    if status == "pending":
        keyboard.append([InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_{payment_id}"), InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{payment_id}")])
    keyboard.append([InlineKeyboardButton("🔙 PENDING", callback_data="pending")])
    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=screenshot,
        caption=f"💳 PAYMENT #{payment_id}\n👤 {target}\n💰 ₹{money(amount)}\n📌 {status.upper()}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await safe_edit(query, "📸 Screenshot sent.", back_button("pending"))

async def approve_payment(query, context, payment_id):
    if not is_admin(query.from_user.id):
        return
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT chat_id, amount, status FROM payments WHERE id=?", (payment_id,))
            payment = cur.fetchone()
            if not payment or payment[2] != "pending":
                await query.answer("Already processed.", True)
                return
            target, amount, _ = payment
            cur.execute("UPDATE payments SET status='approved' WHERE id=? AND status='pending'", (payment_id,))
            if cur.rowcount != 1:
                await query.answer("Failed.", True)
                return
            cur.execute("UPDATE users SET balance=balance+? WHERE chat_id=?", (amount, target))
            cur.execute("SELECT balance FROM users WHERE chat_id=?", (target,))
            new_balance = cur.fetchone()[0]
        await query.answer("Approved.")
        await safe_edit(query,
            f"✅ PAYMENT APPROVED\n\n🆔 #{payment_id}\n👤 {target}\n💰 Added: ₹{money(amount)}\n💳 Balance: ₹{money(new_balance)}",
            back_button("pending"))
        await send_message_safe(context.bot, target, f"🎉 Payment approved! ₹{money(amount)} added. New balance: ₹{money(new_balance)}")
        first, username, display = get_user_display(target)
        await send_message_safe(context.bot, ADMIN_CHAT_ID,
            f"✅ **MANUAL APPROVE**\n"
            f"👤 {display} [`{target}`]\n"
            f"💰 Amount: ₹{money(amount)}\n"
            f"💳 New Balance: ₹{money(new_balance)}")
    except Exception as e:
        logger.exception("Approve error")
        await query.answer("Error.", True)

async def reject_payment(query, context, payment_id):
    if not is_admin(query.from_user.id):
        return
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT chat_id, amount FROM payments WHERE id=? AND status='pending'", (payment_id,))
            payment = cur.fetchone()
            if not payment:
                await query.answer("Already processed.", True)
                return
            target, amount = payment
            cur.execute("UPDATE payments SET status='rejected' WHERE id=?", (payment_id,))
        await query.answer("Rejected.")
        await safe_edit(query,
            f"❌ PAYMENT REJECTED\n\n🆔 #{payment_id}\n👤 {target}\n💰 ₹{money(amount)}",
            back_button("pending"))
        await send_message_safe(context.bot, target, f"❌ Payment of ₹{money(amount)} rejected. Contact support.")
    except Exception as e:
        logger.exception("Reject error")
        await query.answer("Error.", True)

# ============================================================
# ADMIN TEXT HANDLER
# ============================================================
async def handle_admin_text(update, context):
    uid = update.effective_user.id
    if not is_admin(uid):
        return False
    state = context.user_data.get("admin_state")
    text = update.message.text.strip()

    if state == "stock_keys":
        await add_stock_text(update, context)
        return True

    if state == "add_reseller_simple":
        try:
            target = int(text)
        except:
            await update.message.reply_text("❌ Invalid Chat ID. Please send a numeric ID.")
            return True
        if target == ADMIN_CHAT_ID:
            await update.message.reply_text("❌ Admin is already admin.")
            context.user_data.clear()
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("INSERT OR IGNORE INTO users (chat_id, role, created_at) VALUES (?, 'reseller', ?)",
                        (target, now()))
            cur.execute("UPDATE users SET role='reseller' WHERE chat_id=?", (target,))
        context.user_data.clear()
        await send_message_safe(update.get_bot(), target,
            f"🎉 You have been promoted to **Reseller**!\nYou now have access to reseller prices.")
        await update.message.reply_text(f"✅ Reseller added. Notification sent.")
        return True

    if state == "remove_reseller":
        try:
            target = int(text)
        except:
            await update.message.reply_text("❌ Invalid Chat ID.")
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET role='user' WHERE chat_id=? AND role='reseller'", (target,))
            changed = cur.rowcount
        context.user_data.clear()
        await update.message.reply_text("✅ RESELLER REMOVED." if changed else "❌ RESELLER NOT FOUND.")
        return True

    if state == "reseller_price":
        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text("❌ Format: RESELLER_ID PRODUCT_ID PRICE")
            return True
        try:
            reseller_id = int(parts[0])
            product_id = int(parts[1])
            price = float(parts[2])
        except:
            await update.message.reply_text("❌ Invalid numbers.")
            return True
        if price < 0:
            await update.message.reply_text("❌ Price cannot be negative.")
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT role FROM users WHERE chat_id=?", (reseller_id,))
            row = cur.fetchone()
            if not row or row[0] != "reseller":
                await update.message.reply_text("❌ Reseller not found.")
                return True
            cur.execute("SELECT id FROM products WHERE id=?", (product_id,))
            if not cur.fetchone():
                await update.message.reply_text("❌ Product not found.")
                return True
            cur.execute("INSERT OR REPLACE INTO reseller_prices (reseller_id, product_id, price) VALUES (?, ?, ?)",
                        (reseller_id, product_id, price))
        context.user_data.clear()
        await update.message.reply_text(f"✅ Custom price set: Reseller {reseller_id}, Product {product_id} → ₹{money(price)}")
        return True

    if state == "wallet":
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("❌ FORMAT: CHAT_ID +500")
            return True
        try:
            target = int(parts[0])
            amount = float(parts[1])
        except:
            await update.message.reply_text("❌ Invalid input.")
            return True
        if target == ADMIN_CHAT_ID and amount < 0:
            await update.message.reply_text("❌ Cannot reduce admin balance.")
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT balance FROM users WHERE chat_id=?", (target,))
            row = cur.fetchone()
            if not row:
                await update.message.reply_text("❌ User not found.")
                return True
            if amount < 0:
                cur.execute("UPDATE users SET balance=balance+? WHERE chat_id=? AND balance>=?", (amount, target, abs(amount)))
            else:
                cur.execute("UPDATE users SET balance=balance+? WHERE chat_id=?", (amount, target))
            if cur.rowcount != 1:
                await update.message.reply_text("❌ Insufficient balance or user not found.")
                return True
            cur.execute("SELECT balance FROM users WHERE chat_id=?", (target,))
            new_balance = cur.fetchone()[0]
        context.user_data.clear()
        await update.message.reply_text(f"✅ WALLET UPDATED\n\n🆔 {target}\n💰 Change: ₹{money(amount)}\n💳 New Balance: ₹{money(new_balance)}")
        await send_message_safe(update.get_bot(), target, f"💰 WALLET UPDATED\n\n💳 New Balance: ₹{money(new_balance)}")
        return True

    if state == "block":
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("FORMAT: CHAT_ID block/unblock")
            return True
        try:
            target = int(parts[0])
            action = parts[1].lower()
            if action not in ("block", "unblock"):
                await update.message.reply_text("Use block or unblock.")
                return True
            if target == ADMIN_CHAT_ID:
                await update.message.reply_text("❌ Cannot block admin.")
                return True
            val = 1 if action == "block" else 0
            with db() as con:
                cur = con.cursor()
                cur.execute("UPDATE users SET blocked=? WHERE chat_id=?", (val, target))
                if cur.rowcount:
                    await update.message.reply_text(f"✅ {action.upper()}D\n\n🆔 {target}")
                else:
                    await update.message.reply_text("❌ User not found.")
            context.user_data.clear()
            return True
        except:
            await update.message.reply_text("❌ Invalid input.")
            return True

    if state == "message":
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            await update.message.reply_text("FORMAT: CHAT_ID MESSAGE")
            return True
        try:
            target = int(parts[0])
            msg = parts[1]
        except:
            await update.message.reply_text("❌ Invalid Chat ID.")
            return True
        if target == ADMIN_CHAT_ID:
            await update.message.reply_text("❌ Cannot message admin.")
            return True
        sent = await send_message_safe(update.get_bot(), target, msg)
        context.user_data.clear()
        await update.message.reply_text("✅ MESSAGE SENT." if sent else "❌ MESSAGE FAILED.")
        return True

    if state == "announcement":
        if not text:
            await update.message.reply_text("❌ Message empty.")
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT chat_id FROM users WHERE blocked=0")
            users = [row[0] for row in cur.fetchall()]
        context.user_data.clear()
        sent = await broadcast_message(update.get_bot(), users, f"📢 ANNOUNCEMENT\n\n{text}")
        await update.message.reply_text(f"✅ Announcement sent to {sent} users.")
        return True

    if state == "wait_welcome_video":
        if len(text) > 20 and re.match(r'^[A-Za-z0-9_\-]+$', text):
            set_setting("welcome_video", text)
            context.user_data.pop("admin_state", None)
            await update.message.reply_text(
                f"✅ Welcome video updated!\nNew File ID: `{text}`",
                reply_markup=admin_panel()
            )
            return True
        else:
            await update.message.reply_text("❌ Invalid File ID. Please send a video or a valid File ID.")
            return True

    if state in ("user_add_balance", "user_remove_balance", "user_set_balance"):
        target = context.user_data.get("target_user")
        amount = safe_float(text)
        if amount is None or amount < 0:
            await update.message.reply_text("❌ Enter a positive number.")
            return True
        if not target:
            context.user_data.clear()
            return True
        with db() as con:
            cur = con.cursor()
            if state == "user_add_balance":
                cur.execute("UPDATE users SET balance=balance+? WHERE chat_id=?", (amount, target))
            elif state == "user_remove_balance":
                cur.execute("UPDATE users SET balance=balance-? WHERE chat_id=? AND balance>=?", (amount, target, amount))
            else:
                cur.execute("UPDATE users SET balance=? WHERE chat_id=?", (amount, target))
            if cur.rowcount != 1:
                await update.message.reply_text("❌ User not found or insufficient balance.")
                return True
            cur.execute("SELECT balance FROM users WHERE chat_id=?", (target,))
            new_balance = cur.fetchone()[0]
        context.user_data.clear()
        action_text = "ADDED" if state == "user_add_balance" else "REMOVED" if state == "user_remove_balance" else "SET"
        await update.message.reply_text(f"✅ BALANCE {action_text}\n\n🆔 {target}\n💳 ₹{money(new_balance)}")
        await send_message_safe(update.get_bot(), target, f"💰 BALANCE UPDATED\n\n💳 New Balance: ₹{money(new_balance)}")
        return True

    if state == "change_normal_price":
        pid = context.user_data.get("change_normal_pid")
        if not pid:
            context.user_data.clear()
            await update.message.reply_text("❌ Session expired. Try again.")
            return True
        try:
            val = float(text)
            if val < 0:
                await update.message.reply_text("❌ Price cannot be negative.")
                return True
        except:
            await update.message.reply_text("❌ Please send a valid number.")
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("UPDATE products SET price=? WHERE id=?", (val, pid))
            if cur.rowcount == 0:
                await update.message.reply_text("❌ Product not found.")
                context.user_data.clear()
                return True
        context.user_data.clear()
        await update.message.reply_text(f"✅ Normal Price updated to ₹{money(val)}!", reply_markup=admin_panel())
        return True

    if state == "change_reseller_price":
        pid = context.user_data.get("change_reseller_pid")
        if not pid:
            context.user_data.clear()
            await update.message.reply_text("❌ Session expired. Try again.")
            return True
        try:
            val = float(text)
            if val < 0:
                await update.message.reply_text("❌ Price cannot be negative.")
                return True
        except:
            await update.message.reply_text("❌ Please send a valid number.")
            return True
        with db() as con:
            cur = con.cursor()
            cur.execute("UPDATE products SET price_bronze=? WHERE id=?", (val, pid))
            if cur.rowcount == 0:
                await update.message.reply_text("❌ Product not found.")
                context.user_data.clear()
                return True
        context.user_data.clear()
        await update.message.reply_text(f"✅ Global Reseller Price updated to ₹{money(val)}!", reply_markup=admin_panel())
        return True

    parts = text.split()
    if len(parts) == 2:
        try:
            pid = int(parts[0])
            price = float(parts[1])
            if price >= 0:
                with db() as con:
                    cur = con.cursor()
                    cur.execute("UPDATE products SET price=? WHERE id=?", (price, pid))
                    if cur.rowcount:
                        await update.message.reply_text(f"✅ PRICE UPDATED\n\n🆔 {pid}\n💰 ₹{money(price)}")
                        context.user_data.clear()
                        return True
        except:
            pass
    return False

# ============================================================
# TEXT HANDLER
# ============================================================
async def text_handler(update, context):
    user = update.effective_user
    register_user(user)
    uid = user.id
    if is_blocked(uid):
        return
    if not rate_limit(uid):
        await update.message.reply_text("⏳ Slow down! Please wait a moment before sending more commands.")
        return
    if is_admin(uid):
        handled = await handle_admin_text(update, context)
        if handled:
            return
    if context.user_data.get("state") == "fund_amount":
        amount = safe_float(update.message.text.strip())
        if amount is None or amount < 1:
            await update.message.reply_text("❌ Enter a valid amount (>= ₹1).")
            return
        if amount > 100000:
            await update.message.reply_text("❌ Amount too large.")
            return
        context.user_data["amount"] = amount
        context.user_data["state"] = "waiting_photo"
        sent = await send_qr(update, amount, context)
        if not sent:
            context.user_data.clear()

# ============================================================
# VIDEO HANDLER
# ============================================================
async def video_handler(update, context):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if context.user_data.get("admin_state") != "wait_welcome_video":
        return
    video = update.message.video
    if video:
        file_id = video.file_id
        set_setting("welcome_video", file_id)
        context.user_data.pop("admin_state", None)
        await update.message.reply_text(
            f"✅ Welcome video updated!\nNew File ID: `{file_id}`",
            reply_markup=admin_panel()
        )
    else:
        await update.message.reply_text("❌ Please send a video file.")

# ============================================================
# CALLBACK HANDLER
# ============================================================
async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data
    register_user(query.from_user)

    if not rate_limit(uid):
        await query.answer("Slow down!", show_alert=True)
        return

    if is_blocked(uid):
        await safe_edit(query, "🚫 Your account is blocked.")
        return

    if data == "leaderboard":
        await leaderboard_page(query)
        return

    if data == "toggle_auto":
        if not is_admin(uid):
            await query.answer("Admin only.", True)
            return
        current = get_setting("auto_verify")
        new_val = "0" if current == "1" else "1"
        set_setting("auto_verify", new_val)
        status = "ON" if new_val == "1" else "OFF"
        await query.answer(f"Auto-Verify is now {status}", show_alert=True)
        await safe_edit(query, "👑 ADMIN PANEL\n\nAuto-Verify: " + status, admin_panel())
        return

    if data == "admin":
        if not is_admin(uid):
            await query.answer("Admin only.", True)
            return
        context.user_data.clear()
        await safe_edit(query, "👑 ADMIN PANEL", admin_panel())
        return

    if data == "users":
        if not is_admin(uid):
            return
        await admin_users(query)
        return

    if data == "reseller_list":
        if not is_admin(uid):
            return
        await reseller_list_page(query)
        return

    if data.startswith("useradd_") or data.startswith("userremove_") or data.startswith("userset_"):
        if not is_admin(uid):
            return
        target = int(data.split("_")[1])
        action = data.split("_")[0]
        context.user_data.clear()
        context.user_data["admin_state"] = action
        context.user_data["target_user"] = target
        label = "ADD BALANCE" if action == "useradd" else "REMOVE BALANCE" if action == "userremove" else "SET BALANCE"
        await safe_edit(query, f"{label}\n\nUser: {target}\n\nEnter amount:", back_button(f"user_{target}"))
        return

    if data.startswith("userblock_"):
        if not is_admin(uid):
            return
        target = int(data.split("_", 1)[1])
        if target == ADMIN_CHAT_ID:
            await query.answer("Can't block admin.", True)
            return
        with db() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET blocked=1 WHERE chat_id=?", (target,))
        await query.answer("Blocked.")
        await admin_user_details(query, target)
        return

    if data.startswith("userunblock_"):
        if not is_admin(uid):
            return
        target = int(data.split("_", 1)[1])
        with db() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET blocked=0 WHERE chat_id=?", (target,))
        await query.answer("Unblocked.")
        await admin_user_details(query, target)
        return

    if data.startswith("user_"):
        if not is_admin(uid):
            return
        target = int(data.split("_", 1)[1])
        await admin_user_details(query, target)
        return

    if data == "change_normal":
        if not is_admin(uid):
            return
        context.user_data.clear()
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT id, name, duration FROM products ORDER BY name")
            prods = cur.fetchall()
        if not prods:
            await safe_edit(query, "❌ No products found.", reply_markup=back_button("admin"))
            return
        buttons = []
        for pid, name, duration in prods:
            buttons.append([InlineKeyboardButton(f"{name} - {duration}", callback_data=f"normal_price_{pid}")])
        buttons.append([InlineKeyboardButton("🔙 BACK", callback_data="admin")])
        await safe_edit(query, "💰 Select product to change **Normal Price**:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("normal_price_"):
        if not is_admin(uid):
            return
        pid = int(data.split("_")[2])
        context.user_data.clear()
        context.user_data["admin_state"] = "change_normal_price"
        context.user_data["change_normal_pid"] = pid
        await safe_edit(query, f"💰 Enter new **Normal Price** for product ID {pid}:", reply_markup=back_button("admin"))
        return

    if data == "change_reseller":
        if not is_admin(uid):
            return
        context.user_data.clear()
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT id, name, duration FROM products ORDER BY name")
            prods = cur.fetchall()
        if not prods:
            await safe_edit(query, "❌ No products found.", reply_markup=back_button("admin"))
            return
        buttons = []
        for pid, name, duration in prods:
            buttons.append([InlineKeyboardButton(f"{name} - {duration}", callback_data=f"reseller_global_{pid}")])
        buttons.append([InlineKeyboardButton("🔙 BACK", callback_data="admin")])
        await safe_edit(query, "💎 Select product to set **Global Reseller Price**:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("reseller_global_"):
        if not is_admin(uid):
            return
        pid = int(data.split("_")[2])
        context.user_data.clear()
        context.user_data["admin_state"] = "change_reseller_price"
        context.user_data["change_reseller_pid"] = pid
        await safe_edit(query, f"💎 Enter new **Global Reseller Price** for product ID {pid}:\n(0 means fallback to normal price)", reply_markup=back_button("admin"))
        return

    if data == "reseller_price":
        if not is_admin(uid):
            return
        await reseller_price_page(query, context)
        return

    if data == "add_reseller":
        if not is_admin(uid):
            return
        await add_reseller_page(query, context)
        return

    if data == "remove_reseller":
        if not is_admin(uid):
            return
        await remove_reseller_page(query, context)
        return

    if data == "buy":
        context.user_data.clear()
        await show_buy(query)
        return

    if data.startswith("engine_"):
        engine = data.split("_", 1)[1]
        await show_engine(query, engine)
        return

    if data == "game_KOS_CARROM":
        await show_plans(query, uid, "KOS")
        return

    if data.startswith("plan_"):
        pid = int(data.split("_", 1)[1])
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT id, name, duration FROM products WHERE id=?", (pid,))
            product = cur.fetchone()
            if not product:
                await safe_edit(query, "❌ Product not found.", back_button("buy"))
                return
            cur.execute("SELECT COUNT(*) FROM stock WHERE product_id=? AND status='available'", (pid,))
            stock_count = cur.fetchone()[0]
            price = get_price(uid, pid)
            user = get_user(uid)
            balance = float(user[3]) if user else 0
        await safe_edit(query,
            f"🎯 {product[1]}\n⚡ {product[2]}\n💰 ₹{money(price)}\n💳 ₹{money(balance)}\n📦 Stock: {stock_count}\n\nConfirm?",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_{pid}")],
                [InlineKeyboardButton("🔙 BACK", callback_data=f"engine_{product[1]}")]
            ]))
        return

    if data.startswith("confirm_"):
        pid = int(data.split("_", 1)[1])
        await buy_key(query, context, pid)
        return

    if data == "fund":
        await fund_menu(query, context)
        return

    if data == "account":
        await account_page(query)
        return

    if data == "history":
        await history_page(query)
        return

    if data == "support":
        await safe_edit(query, f"📞 Support: {SUPPORT}", back_button())
        return

    if data == "check_stock":
        with db() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT p.name, p.duration, COUNT(s.id) as available
                FROM products p
                LEFT JOIN stock s ON s.product_id = p.id AND s.status = 'available'
                GROUP BY p.id
                ORDER BY p.name, p.id
            """)
            rows = cur.fetchall()
        if not rows:
            await safe_edit(query, "📦 No stock available.", back_button())
            return
        text = "📦 **AVAILABLE STOCK**\n\n"
        for name, duration, count in rows:
            text += f"🎯 {name} – {duration}: **{count} keys**\n"
        await safe_edit(query, text, back_button())
        return

    if data == "send_screenshot":
        context.user_data["state"] = "waiting_photo"
        await query.answer("📸 Please send a screenshot of your payment.", show_alert=True)
        await safe_edit(query,
            "✅ After payment, send a **screenshot** of the UPI transaction.\n\n"
            "Make sure it shows the UPI reference number and amount.\n"
            "Admin will verify and add balance.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 BACK", callback_data="back")]
            ]))
        return

    if data.startswith("copy_key_"):
        purchase_id = int(data.split("_")[2])
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT license_key FROM purchases WHERE id=? AND chat_id=?", (purchase_id, uid))
            row = cur.fetchone()
            if not row:
                await query.answer("Key not found or you didn't purchase this.", show_alert=True)
                return
            key = row[0]
            await context.bot.send_message(
                chat_id=uid,
                text=f"🔑 **Your Key:**\n`{key}`\n\nTap and hold to copy.",
                parse_mode="Markdown"
            )
            await query.answer("✅ Key sent in a separate message!", show_alert=True)
        return

    if data == "wallet":
        if not is_admin(uid):
            return
        await wallet_page(query, context)
        return

    if data == "block":
        if not is_admin(uid):
            return
        await block_page(query, context)
        return

    if data == "message":
        if not is_admin(uid):
            return
        await message_page(query, context)
        return

    if data == "announcement":
        if not is_admin(uid):
            return
        await announcement_page(query, context)
        return

    if data == "add_stock":
        if not is_admin(uid):
            return
        await safe_edit(query, "📦 ADD STOCK\nSelect Engine:", InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 KOS", callback_data="stock_KOS")],
            [InlineKeyboardButton("🐍 SNAKE", callback_data="stock_SNAKE")],
            [InlineKeyboardButton("🤖 AIM AI", callback_data="stock_AIM AI")],
            [InlineKeyboardButton("🔙 ADMIN", callback_data="admin")]
        ]))
        return

    if data.startswith("stockpid_"):
        if not is_admin(uid):
            return
        pid = int(data.split("_", 1)[1])
        await stock_product_page(query, context, pid)
        return

    if data.startswith("stock_"):
        if not is_admin(uid):
            return
        engine = data.split("_", 1)[1]
        await stock_engine_page(query, engine)
        return

    if data == "stock_list":
        if not is_admin(uid):
            return
        await stock_list_page(query)
        return

    if data == "delete_stock":
        if not is_admin(uid):
            return
        await delete_stock_page(query)
        return

    if data.startswith("delstock_"):
        if not is_admin(uid):
            return
        pid = int(data.split("_", 1)[1])
        await delete_stock_product(query, pid)
        return

    if data == "deleteallstock":
        if not is_admin(uid):
            return
        await delete_all_stock(query)
        return

    if data == "products":
        if not is_admin(uid):
            return
        await products_page(query)
        return

    if data == "stats":
        if not is_admin(uid):
            return
        await stats_page(query)
        return

    if data == "pending":
        if not is_admin(uid):
            return
        await pending_page(query)
        return

    if data.startswith("payment_"):
        if not is_admin(uid):
            return
        payment_id = int(data.split("_", 1)[1])
        await payment_view(query, context, payment_id)
        return

    if data.startswith("approve_"):
        if not is_admin(uid):
            return
        payment_id = int(data.split("_", 1)[1])
        await approve_payment(query, context, payment_id)
        return

    if data.startswith("reject_"):
        if not is_admin(uid):
            return
        payment_id = int(data.split("_", 1)[1])
        await reject_payment(query, context, payment_id)
        return

    if data == "change_welcome_video":
        if not is_admin(uid):
            return
        context.user_data.clear()
        context.user_data["admin_state"] = "wait_welcome_video"
        await safe_edit(query,
            "🎥 **CHANGE WELCOME VIDEO**\n\n"
            "Send a **video** or paste a **File ID**.\n"
            "The bot will use it as the new welcome video for all new users.\n\n"
            "To cancel, click BACK.",
            reply_markup=back_button("admin"))
        return

    if data == "reseller":
        if not is_reseller(uid):
            await query.answer("You are not a reseller.", True)
            return
        user = get_user(uid)
        await safe_edit(query,
            f"🤝 RESELLER PANEL\n\n💰 Balance: ₹{money(user[3])}\n\nUse BUY ENGINE.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 BUY ENGINE", callback_data="buy")],
                [InlineKeyboardButton("👤 ACCOUNT", callback_data="account")],
                [InlineKeyboardButton("🔙 BACK", callback_data="back")]
            ]))
        return

    if data == "back":
        context.user_data.clear()
        user = get_user(uid)
        balance = user[3] if user else 0
        await safe_edit(query, f"🏠 YASHU STORE\n\n💰 Balance: ₹{money(balance)}", main_menu(uid))
        return

    if data == "copy_unavailable":
        await query.answer("Copy not supported. Key shown above.", True)
        return

    await query.answer("Unknown action.", True)

# ============================================================
# START
# ============================================================
async def start(update, context):
    if not update.effective_user or not update.message:
        return
    user = update.effective_user
    register_user(user)
    uid = user.id
    context.user_data.clear()
    if is_blocked(uid):
        await update.message.reply_text("🚫 YOUR ACCOUNT IS BLOCKED.\n\n📞 Please contact support.")
        return

    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT bonus_claimed FROM users WHERE chat_id=?", (uid,))
            row = cur.fetchone()
            if row and row[0] == 0:
                cur.execute("UPDATE users SET balance = balance + 20, bonus_claimed = 1 WHERE chat_id=?", (uid,))
                await update.message.reply_text("🎉 Welcome! You received ₹20 bonus on sign-up!")
    except Exception as e:
        logger.exception("Bonus error")

    row = get_user(uid)
    first_name = row[2] if row and row[2] else user.first_name or "User"
    balance = float(row[3]) if row else 0
    role = row[4] if row else "user"
    try:
        with db() as con:
            cur = con.cursor()
            cur.execute("SELECT COALESCE(SUM(price), 0) FROM purchases WHERE chat_id=?", (uid,))
            lifetime = float(cur.fetchone()[0] or 0)
    except:
        lifetime = 0

    welcome_text = (
        "╔══════════════════════════╗\n"
        " ✨ WELCOME TO ✨\n"
        " 🔥 YASHU STORE 🔥\n"
        "╚══════════════════════════╝\n\n"
        f"👋 Hey, {first_name}! 🚀\n\n"
        "🎮 PREMIUM ENGINE STORE\n"
        "⚡ Fast • Secure • Reliable\n"
        "🔑 Instant Key Delivery\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 YOUR ACCOUNT\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Balance: ₹{money(balance)}\n"
        f"💎 Lifetime Spend: ₹{money(lifetime)}\n"
        f"👑 Role: {role.upper()}\n"
        f"🏷️ {'Reseller' if role == 'reseller' else 'User'}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 AVAILABLE ENGINES\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 KOS ENGINE\n"
        "🐍 SNAKE ENGINE\n"
        "🤖 AIM AI ENGINE\n\n"
        "👇 Select an option below"
    )

    welcome_video = get_setting("welcome_video")
    if welcome_video:
        try:
            await update.message.reply_video(
                video=welcome_video,
                caption=welcome_text,
                reply_markup=main_menu(uid)
            )
            return
        except Exception as e:
            logger.warning(f"Welcome video failed: {e}")

    await update.message.reply_text(welcome_text, reply_markup=main_menu(uid))

# ============================================================
# ERROR HANDLER
# ============================================================
async def error_handler(update, context):
    error = context.error
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning("Network error: %r", error)
        return
    if isinstance(error, RetryAfter):
        logger.warning("Rate limit: %s", error.retry_after)
        return
    if isinstance(error, BadRequest):
        logger.warning("Bad request: %r", error)
        return
    logger.exception("Unhandled error: %r", error)

# ============================================================
# MAIN
# ============================================================
async def post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning("delete_webhook failed: %r", e)

    app.bot_data["background_tasks"] = [
        asyncio.create_task(background_verifier(app.bot), name="background_verifier"),
        asyncio.create_task(rate_limit_cleanup(), name="rate_limit_cleanup"),
    ]
    logger.info("Background tasks started.")

async def post_shutdown(app):
    tasks = app.bot_data.get("background_tasks", [])
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Background tasks stopped.")

def main():
    if not BOT_TOKEN:
        print("\n❌ ERROR: BOT_TOKEN is not set.")
        print("Set BOT_TOKEN in your hosting environment/secret variables.")
        return
    if ADMIN_CHAT_ID <= 0:
        print("\n❌ ERROR: ADMIN_CHAT_ID is not set correctly.")
        print("Set ADMIN_CHAT_ID in your hosting environment/secret variables.")
        return

    if not QR_LIBS_OK:
        logger.warning("QR libraries are missing. Install dependencies from requirements.txt.")

    print("🔧 Setting up database...")
    try:
        setup_db()
    except Exception as e:
        logger.exception("DATABASE SETUP FAILED: %r", e)
        return

    print("🔧 Starting bot...")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))
    app.add_error_handler(error_handler)

    print("========================================")
    print("🔥 YASHU STORE BOT STARTED")
    print(f"✅ Database path: {DB}")
    print("✅ Asyncio lifecycle: hosting-safe")
    print("✅ Auto-verify background task configured")
    print("✅ Rate limiting active")
    print("✅ Welcome Video – Admin can change via panel")
    print("✅ All callback routes preserved")
    print(f"👑 ADMIN: {ADMIN_CHAT_ID}")
    print("========================================")

    app.run_polling(drop_pending_updates=True, close_loop=True)

if __name__ == "__main__":
    main()