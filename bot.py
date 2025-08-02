import logging
import sqlite3
import requests
import datetime
import asyncio
from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update,
    InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ========== CONFIGURATION ==========
BOT_TOKEN = '7939176482:AAEWQkAtjqTJ2JY5YRRN9XsUS8AWy3kKoJI'
ADMIN_ID = 1362321291
NOWPAYMENTS_API_KEY = 'BJMQ1ZZ-K8JMX4G-GY0EP0N-V210854'
KYC_PRICE = 20
WEBAPP_URL = "https://coinspark.pro/kyc/index.php"
VOUCH_CHANNEL_ID = -1002871277227
SUPPORT_USERNAME = "@Fragmentkysupportbot"
DATABASE_NAME = "fragment_kyc.db"

# Supported cryptocurrencies
CRYPTOCURRENCIES = [
    'btc', 'eth', 'usdt', 'usdc', 'xmr', 'ton', 'sol', 'trx',
    'dai', 'dash', 'xrp', 'bch', 'ltc', 'ada', 'doge', 'matic',
    'dot', 'shib', 'avax', 'link', 'atom', 'xlm', 'uni', 'fil'
]

# ========== LOGGING SETUP ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== DATABASE FUNCTIONS ==========
def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        registration_date TEXT,
        last_active TEXT,
        is_admin BOOLEAN DEFAULT 0
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount REAL,
        currency TEXT,
        status TEXT,
        invoice_url TEXT,
        tx_hash TEXT,
        timestamp TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    ''')  # Added missing closing parenthesis
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        status TEXT,
        order_date TEXT,
        completion_date TEXT,
        details TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_stats (
        stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_users INTEGER DEFAULT 0,
        total_payments REAL DEFAULT 0,
        total_orders INTEGER DEFAULT 0,
        last_updated TEXT
    )
    ''')
    
    # Insert admin user if not exists
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (ADMIN_ID,))
    if not cursor.fetchone():
        cursor.execute('''
        INSERT INTO users (user_id, username, balance, registration_date, last_active, is_admin)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (ADMIN_ID, "admin", 0, datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat(), 1))
    
    conn.commit()
    conn.close()

# Initialize database
init_db()

# ========== DATABASE OPERATIONS ==========
def get_user(user_id):
    """Get user data from database"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user(user_id, username=None, balance=None, is_admin=False):
    """Update or create user in database"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().isoformat()
    
    user = get_user(user_id)
    if not user:
        cursor.execute('''
        INSERT INTO users (user_id, username, balance, registration_date, last_active, is_admin)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username or str(user_id), balance or 0, now, now, is_admin))
    else:
        if balance is not None:
            cursor.execute('''
            UPDATE users 
            SET balance = ?, last_active = ?, username = COALESCE(?, username), is_admin = ?
            WHERE user_id = ?
            ''', (balance, now, username, is_admin, user_id))
        else:
            cursor.execute('''
            UPDATE users 
            SET last_active = ?, username = COALESCE(?, username), is_admin = ?
            WHERE user_id = ?
            ''', (now, username, is_admin, user_id))
    
    conn.commit()
    conn.close()

def create_payment(user_id, payment_id, amount, currency, status, invoice_url):
    """Create a new payment record"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO payments (payment_id, user_id, amount, currency, status, invoice_url, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (payment_id, user_id, amount, currency, status, invoice_url, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_payment(payment_id, status, tx_hash=None):
    """Update payment status"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    if tx_hash:
        cursor.execute('''
        UPDATE payments SET status = ?, tx_hash = ? WHERE payment_id = ?
        ''', (status, tx_hash, payment_id))
    else:
        cursor.execute('''
        UPDATE payments SET status = ? WHERE payment_id = ?
        ''', (status, payment_id))
    conn.commit()
    conn.close()

def create_order(user_id, details=None):
    """Create a new KYC order"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO orders (user_id, status, order_date, details)
    VALUES (?, ?, ?, ?)
    ''', (user_id, 'pending', datetime.datetime.now().isoformat(), details or ''))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def complete_order(order_id):
    """Mark an order as completed"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE orders 
    SET status = 'completed', completion_date = ?
    WHERE order_id = ?
    ''', (datetime.datetime.now().isoformat(), order_id))
    conn.commit()
    conn.close()

def get_user_payments(user_id, limit=10):
    """Get user payment history"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT * FROM payments 
    WHERE user_id = ? 
    ORDER BY timestamp DESC 
    LIMIT ?
    ''', (user_id, limit))
    payments = cursor.fetchall()
    conn.close()
    return payments

def get_user_orders(user_id, limit=5):
    """Get user order history"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT * FROM orders 
    WHERE user_id = ? 
    ORDER BY order_date DESC 
    LIMIT ?
    ''', (user_id, limit))
    orders = cursor.fetchall()
    conn.close()
    return orders

def get_admin_stats():
    """Get statistics for admin panel"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(amount) FROM payments WHERE status = "completed"')
    total_payments = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM orders')
    total_orders = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'total_users': total_users,
        'total_payments': total_payments,
        'total_orders': total_orders,
        'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    }

def update_admin_stats():
    """Update admin statistics"""
    stats = get_admin_stats()
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO admin_stats (total_users, total_payments, total_orders, last_updated)
    VALUES (?, ?, ?, ?)
    ''', (stats['total_users'], stats['total_payments'], stats['total_orders'], stats['last_updated']))
    conn.commit()
    conn.close()

# ========== PAYMENT FUNCTIONS ==========
async def create_invoice(user_id, coin_code):
    """Create a payment invoice with NowPayments"""
    try:
        url = "https://api.nowpayments.io/v1/invoice"
        headers = {
            "x-api-key": NOWPAYMENTS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "price_amount": KYC_PRICE,
            "price_currency": "usd",
            "pay_currency": coin_code,
            "ipn_callback_url": f"{WEBAPP_URL}/callback",
            "order_id": f"KYC_{user_id}_{datetime.datetime.now().timestamp()}",
            "order_description": "Fragment KYC Verification",
            "success_url": f"https://t.me/Fragmentkyczbot?start=success_{user_id}",
            "cancel_url": f"https://t.me/Fragmentkyczbot?start=cancel_{user_id}"
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'invoice_url' not in data:
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Invoice creation error: {error_msg}")
            if "Currency" in error_msg and "not supported" in error_msg:
                return None, "This cryptocurrency is not currently supported for payments."
            return None, "Payment creation failed. Please try another method."
            
        return data, None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Invoice creation request failed: {str(e)}")
        return None, "Payment service is currently unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, "An unexpected error occurred during payment processing. Please try again."

async def check_payment_status(payment_id):
    """Check payment status with NowPayments"""
    try:
        url = f"https://api.nowpayments.io/v1/payment/{payment_id}"
        headers = {"x-api-key": NOWPAYMENTS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Payment check response: {data}")
            
            status = data.get("payment_status", "").lower()
            if status in ['finished', 'confirmed', 'completed']:
                return True, data
            
            pay_amount = float(data.get("pay_amount", 0))
            actually_paid = float(data.get("actually_paid", 0))
            if actually_paid >= pay_amount:
                return True, data
                
            return False, data
        else:
            logger.error(f"Payment check error: {response.status_code} - {response.text}")
            return False, None
    except Exception as e:
        logger.error(f"Payment check exception: {str(e)}")
        return False, None

# ========== KEYBOARD COMPONENTS ==========
def back_button():
    """Return a simple back button"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

def support_button():
    """Return support options with back button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Contact Support", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])

def admin_panel_buttons():
    """Return admin panel navigation buttons"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📩 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("💳 Payment Logs", callback_data="admin_payments")],
        [InlineKeyboardButton("📦 Order Management", callback_data="admin_orders")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back")]
    ])

def crypto_payment_buttons():
    """Return buttons for cryptocurrency selection"""
    buttons = []
    row = []
    for i, crypto in enumerate(CRYPTOCURRENCIES):
        row.append(InlineKeyboardButton(crypto.upper(), callback_data=f'pay_{crypto}'))
        if (i + 1) % 4 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
    return InlineKeyboardMarkup(buttons)

# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id
    username = user.username or str(user_id)
    
    # Update user in database
    update_user(user_id, username)
    
    # Handle payment callback
    if update.message and update.message.text.startswith('/start success_'):
        payment_id = f"success_{datetime.datetime.now().timestamp()}"
        create_payment(user_id, payment_id, KYC_PRICE, 'USD', 'completed', '')
        
        # Update user balance
        user_data = get_user(user_id)
        new_balance = (user_data[2] if user_data else 0) + KYC_PRICE
        update_user(user_id, balance=new_balance)
        
        await update.message.reply_text(
            f"✅ Payment successful! ${KYC_PRICE} has been credited to your account balance.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Order KYC Verification", callback_data='order')],
                [InlineKeyboardButton("📜 Transaction History", callback_data='history')],
                [InlineKeyboardButton("🆘 Support", callback_data='support')]
            ])
        )
        return
    
    # Main menu keyboard
    keyboard = [
        [InlineKeyboardButton("💰 Account Balance", callback_data='balance'),
         InlineKeyboardButton("💵 Deposit Funds", callback_data='deposit')],
        [InlineKeyboardButton("🛒 Order KYC ($20)", callback_data='order')],
        [InlineKeyboardButton("📜 Transaction History", callback_data='history')],
        [InlineKeyboardButton("🆘 Support", callback_data='support')]
    ]
    
    # Add admin panel button for admin
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👨‍💻 Admin Panel", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """✨ *Welcome to Fragment KYC Verification Service* ✨

🔐 *Secure & Reliable KYC Solutions*
✅ Trusted by thousands of users worldwide
⚡ Lightning-fast verification processing

💼 *How Our Service Works:*
1️⃣ Deposit $20 for each verification
2️⃣ Submit your required details securely
3️⃣ Receive verification within minutes

📊 *Service Benefits:*
• 99.9% Success Rate
• 24/7 Customer Support
• Fully Encrypted Data Handling

🌐 *Community & Support:*
Official Channel: @Fragmentkyc
Support: @Fragmentkysupportbot

🔹 Ready to begin? Use the menu below to get started."""
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel access"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Access denied", show_alert=True)
        return
    
    stats = get_admin_stats()
    stats_text = f"""📊 *Admin Statistics*

👥 Total Users: *{stats['total_users']}*
💰 Total Payments: *${stats['total_payments']:.2f}*
📦 Total Orders: *{stats['total_orders']}*
🔄 Last Updated: *{stats['last_updated']}*"""
    
    await query.edit_message_text(
        stats_text,
        reply_markup=admin_panel_buttons(),
        parse_mode='Markdown'
    )

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle support requests"""
    query = update.callback_query
    await query.answer()
    
    support_text = """🆘 *Fragment KYC Support Center*

Our dedicated support team is available 24/7 to assist you with any questions or issues.

📌 *Common Support Topics:*
• Payment verification issues
• KYC process guidance
• Account balance inquiries
• Service questions

💬 *Contact Options:*
1. Live chat with our support team
2. Direct message @Fragmentkysupportbot
3. Email support@fragmentkyc.com

⚠️ For urgent issues, please use the live chat option below."""

    await query.edit_message_text(
        support_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Live Chat with Support", callback_data='chat_support')],
            [InlineKeyboardButton("✉️ Message Support Bot", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data='back')]
        ]),
        parse_mode='Markdown'
    )

async def chat_support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle support chat initiation"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    # Check user balance
    user_data = get_user(user_id)
    balance = user_data[2] if user_data else 0
    
    if balance >= KYC_PRICE:
        # Start support chat
        update_user(user_id, balance=balance - KYC_PRICE)
        
        await query.edit_message_text(
            "💬 *Connecting you with Fragment KYC Support*\n\n"
            "A support representative will be with you shortly. Please describe your issue in detail.\n\n"
            "Type /endchat to disconnect at any time.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Support", callback_data='support')]
            ]),
            parse_mode='Markdown'
        )
        
        # Notify admin
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆘 Support Request\n👤 User: @{username}\n🆔 ID: {user_id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Accept Chat", callback_data=f"chat_{user_id}")]
            ])
        )
    else:
        await query.edit_message_text(
            "⚠️ *Support Access Requirements*\n\n"
            "To access priority live chat support, you need to have an active balance of $20.\n\n"
            "You can still contact us through our support bot or email for general inquiries.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💵 Deposit Funds", callback_data='deposit')],
                [InlineKeyboardButton("✉️ Message Support", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")],
                [InlineKeyboardButton("🔙 Back", callback_data='support')]
            ]),
            parse_mode='Markdown'
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    try:
        if query.data == "balance":
            user_data = get_user(user_id)
            balance = user_data[2] if user_data else 0
            await query.edit_message_text(
                f"💳 *Account Balance*\n\n"
                f"🔹 Current Balance: *${balance:.2f}*\n"
                f"🔹 KYC Verification Price: *${KYC_PRICE}*",
                reply_markup=back_button(),
                parse_mode='Markdown'
            )

        elif query.data == "deposit":
            await query.edit_message_text(
                "💎 *Select Payment Method*\n\n"
                "Choose from our wide range of supported cryptocurrencies:",
                reply_markup=crypto_payment_buttons(),
                parse_mode='Markdown'
            )

        elif query.data.startswith("pay_"):
            coin = query.data.split("_")[1].lower()
            invoice_data, error_msg = await create_invoice(user_id, coin)
            
            if error_msg:
                await query.edit_message_text(
                    f"❌ *Payment Error*\n\n{error_msg}",
                    reply_markup=back_button(),
                    parse_mode='Markdown'
                )
                return
                
            payment_id = invoice_data.get('id')
            create_payment(user_id, payment_id, KYC_PRICE, coin, 'pending', invoice_data['invoice_url'])
            
            payment_message = f"""
💳 *{coin.upper()} Payment Invoice*

🔹 Amount Due: *${KYC_PRICE} USD*
🔹 Payment ID: `{payment_id}`
🔹 Status: *Pending Payment*

📌 *Payment Instructions:*
1. Click the 'Pay Now' button below
2. Complete payment in the opened window
3. Return here to verify payment status

⚠️ Payments typically process within 10-15 minutes."""
            
            await query.edit_message_text(
                payment_message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Pay Now", url=invoice_data['invoice_url'])],
                    [InlineKeyboardButton("🔄 Check Payment Status", callback_data=f'check_{payment_id}')],
                    [InlineKeyboardButton("🔙 Back to Deposit", callback_data='deposit')]
                ])
            )

        elif query.data.startswith("check_"):
            payment_id = query.data.split("_")[1]
            is_paid, payment_data = await check_payment_status(payment_id)
            
            if is_paid:
                # Update payment status
                update_payment(payment_id, 'completed', payment_data.get('payin_hash'))
                
                # Update user balance
                user_data = get_user(user_id)
                new_balance = (user_data[2] if user_data else 0) + KYC_PRICE
                update_user(user_id, balance=new_balance)
                
                await query.edit_message_text(
                    f"✅ *Payment Confirmed!*\n\n"
                    f"🔹 Amount: *${KYC_PRICE}*\n"
                    f"🔹 Transaction: `{payment_data.get('payin_hash', 'N/A')}`\n"
                    f"🔹 New Balance: *${new_balance:.2f}*",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Order KYC", callback_data='order')],
                        [InlineKeyboardButton("📜 History", callback_data='history')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back')]
                    ])
                )
            else:
                await query.edit_message_text(
                    "⌛ *Payment Still Processing*\n\n"
                    "Your payment hasn't been confirmed yet. Please try again in a few minutes.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Check Again", callback_data=f'check_{payment_id}')],
                        [InlineKeyboardButton("🔙 Back", callback_data='deposit')]
                    ]),
                    parse_mode='Markdown'
                )

        elif query.data == "order":
            user_data = get_user(user_id)
            balance = user_data[2] if user_data else 0
            
            if balance >= KYC_PRICE:
                # Deduct balance and create order
                update_user(user_id, balance=balance - KYC_PRICE)
                order_id = create_order(user_id)
                
                await query.edit_message_text(
                    f"✅ *KYC Order Placed!*\n\n"
                    f"🔹 Order ID: `{order_id}`\n"
                    f"🔹 Price: *${KYC_PRICE}*\n"
                    f"🔹 New Balance: *${balance - KYC_PRICE:.2f}*\n\n"
                    "Please provide your details to complete the verification process.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Submit Details", callback_data='submit_details')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back')]
                    ])
                )
                
                # Notify admin
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🆕 New KYC Order\n👤 User: @{username}\n🆔 ID: {user_id}\n🔹 Order ID: {order_id}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Chat", callback_data=f"chat_{user_id}")],
                        [InlineKeyboardButton("✅ Complete", callback_data=f"complete_{order_id}")]
                    ])
                )
            else:
                await query.edit_message_text(
                    "❌ *Insufficient Balance*\n\n"
                    f"You need *${KYC_PRICE}* to place a KYC order.\n"
                    f"Current balance: *${balance:.2f}*",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💵 Deposit Funds", callback_data='deposit')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back')]
                    ])
                )

        elif query.data == "history":
            payments = get_user_payments(user_id)
            orders = get_user_orders(user_id)
            
            history_text = "📜 *Your Transaction History*\n\n"
            
            if payments:
                history_text += "💳 *Payments:*\n"
                for payment in payments[:5]:  # Show last 5 payments
                    history_text += (
                        f"• {payment[7][:10]} - "
                        f"${payment[2]} {payment[3].upper()} - "
                        f"{payment[4].capitalize()}\n"
                    )
            
            if orders:
                history_text += "\n📦 *Orders:*\n"
                for order in orders[:3]:  # Show last 3 orders
                    history_text += (
                        f"• #{order[0]} - "
                        f"{order[2].capitalize()} - "
                        f"{order[3][:10]}\n"
                    )
            
            if not payments and not orders:
                history_text += "No transaction history found."
            
            await query.edit_message_text(
                history_text,
                reply_markup=back_button(),
                parse_mode='Markdown'
            )

        elif query.data == "admin_panel":
            await admin_panel(update, context)

        elif query.data == "support":
            await support_handler(update, context)

        elif query.data == "chat_support":
            await chat_support_handler(update, context)

        elif query.data == "back":
            await start(update, context)

    except Exception as e:
        logger.error(f"Error in button handler: {str(e)}")
        await query.edit_message_text(
            "❌ An unexpected error occurred. Our team has been notified.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Contact Support", callback_data='support')],
                [InlineKeyboardButton("🔙 Back", callback_data='back')]
            ])
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An unexpected error occurred. Please try again later.",
            reply_markup=back_button()
        )

# ========== MAIN APPLICATION ==========
def main() -> None:
    """Start the bot."""
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)
    
    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
