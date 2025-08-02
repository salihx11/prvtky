import logging
import requests
import telegram
import datetime
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Constants
BOT_TOKEN = '7939176482:AAEWQkAtjqTJ2JY5YRRN9XsUS8AWy3kKoJI'
ADMIN_ID = 1362321291
NOWPAYMENTS_API_KEY = 'BJMQ1ZZ-K8JMX4G-GY0EP0N-V210854'
KYC_PRICE = 20
WEBAPP_URL = "https://coinspark.pro/kyc/index.php"
VOUCH_CHANNEL_ID = -1002871277227
MAX_PAYMENT_CHECKS = 3  # Maximum number of times a user can check payment status
CHECK_COOLDOWN = 600    # 10 minutes in seconds
SUPPORT_USERNAME = "@Fragmentkysupportbot"  # Support username

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
user_balances = {}
payment_history = {}
pending_orders = {}
active_chats = {}
broadcast_messages = []
payment_check_attempts = {}  # Track payment check attempts
vouches = {}

# Extended list of supported cryptocurrencies
SUPPORTED_CRYPTOS = [
    'btc', 'eth', 'usdt', 'usdc', 'xmr', 'ton', 'sol', 'trx', 
    'dai', 'dash', 'xrp', 'bch', 'ltc', 'ada', 'doge', 'matic',
    'dot', 'shib', 'avax', 'link', 'atom', 'xlm', 'uni', 'fil'
]

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

def support_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Contact Support", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])

async def create_invoice(user_id, coin_code):
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
    except ValueError as e:
        logger.error(f"Invalid JSON response: {str(e)}")
        return None, "Payment processing error occurred. Please contact support."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, "An unexpected error occurred during payment processing. Please try again."

async def check_payment_status(payment_id):
    try:
        url = f"https://api.nowpayments.io/v1/payment/{payment_id}"
        headers = {"x-api-key": NOWPAYMENTS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Payment check response: {data}")
            
            # Check different status indicators
            status = data.get("payment_status", "").lower()
            if status in ['finished', 'confirmed', 'completed']:
                return True, data
            
            # Check if actually paid meets the required amount
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

async def cleanup_pending_payments():
    """Remove payment records that are too old and still pending"""
    while True:
        try:
            now = datetime.datetime.now()
            to_remove = []
            
            for payment_id, payment in payment_history.items():
                if payment['status'] == 'pending':
                    payment_time = datetime.datetime.fromisoformat(payment['timestamp'])
                    if (now - payment_time).days > 1:  # 1 day old
                        to_remove.append(payment_id)
            
            for payment_id in to_remove:
                del payment_history[payment_id]
                logger.info(f"Cleaned up old pending payment {payment_id}")
                
        except Exception as e:
            logger.error(f"Error in payment cleanup: {str(e)}")
        
        await asyncio.sleep(3600)  # Run once per hour

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text.startswith('/start success_'):
        user_id = int(update.message.text.split('_')[1])
        user_balances[user_id] = user_balances.get(user_id, 0) + KYC_PRICE
        payment_id = f"success_{datetime.datetime.now().timestamp()}"
        payment_history[payment_id] = {
            'user_id': user_id,
            'amount': KYC_PRICE,
            'currency': 'USD',
            'status': 'completed',
            'timestamp': datetime.datetime.now().isoformat()
        }
        await update.message.reply_text(
            f"✅ Payment successful! ${KYC_PRICE} has been credited to your account balance.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Order KYC Verification", callback_data='order')],
                [InlineKeyboardButton("📜 Transaction History", callback_data='history')],
                [InlineKeyboardButton("🆘 Support", callback_data='support')]
            ])
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Account Balance", callback_data='balance'),
         InlineKeyboardButton("💵 Deposit Funds", callback_data='deposit')],
        [InlineKeyboardButton("🛒 Order KYC ($20)", callback_data='order')],
        [InlineKeyboardButton("📜 Transaction History", callback_data='history')],
        [InlineKeyboardButton("🆘 Support", callback_data='support')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = """✨ *Welcome to Fragment KYC Verification Service* ✨

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
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    # Check user balance
    balance = user_balances.get(user_id, 0)
    if balance >= KYC_PRICE:
        # Start support chat
        active_chats[user_id] = ADMIN_ID
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

# [Previous functions like add_balance, broadcast, etc. remain the same, just add the parse_mode='Markdown' parameter where appropriate]

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    try:
        if query.data == "balance":
            balance = user_balances.get(user_id, 0)
            await query.edit_message_text(
                f"💳 *Account Balance*\n\n"
                f"🔹 Current Balance: *${balance:.2f}*\n"
                f"🔹 KYC Verification Price: *${KYC_PRICE}*",
                reply_markup=back_button(),
                parse_mode='Markdown'
            )

        elif query.data == "deposit":
            # Group buttons in rows of 4 for better organization
            buttons = []
            row = []
            for i, crypto in enumerate(SUPPORTED_CRYPTOS):
                row.append(InlineKeyboardButton(crypto.upper(), callback_data=f'pay_{crypto}'))
                if (i + 1) % 4 == 0:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "💎 *Select Payment Method*\n\n"
                "Choose from our wide range of supported cryptocurrencies:",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode='Markdown'
            )

        elif query.data.startswith("pay_"):
            coin = query.data.split("_")[1].lower()
            if coin not in SUPPORTED_CRYPTOS:
                await query.edit_message_text(
                    "❌ *Unsupported Currency*\n"
                    "The selected cryptocurrency is not currently supported.",
                    reply_markup=back_button(),
                    parse_mode='Markdown'
                )
                return
                
            invoice_data, error_msg = await create_invoice(user_id, coin)
            
            if error_msg:
                await query.edit_message_text(
                    f"❌ *Payment Error*\n\n{error_msg}",
                    reply_markup=back_button(),
                    parse_mode='Markdown'
                )
                return
                
            payment_id = invoice_data.get('id')
            payment_history[payment_id] = {
                'user_id': user_id,
                'amount': KYC_PRICE,
                'currency': coin,
                'status': 'pending',
                'timestamp': datetime.datetime.now().isoformat(),
                'invoice_url': invoice_data['invoice_url']
            }
            
            # Reset payment check attempts
            payment_check_attempts[user_id] = 0
            
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

        elif query.data == "support":
            await support_handler(update, context)

        elif query.data == "chat_support":
            await chat_support_handler(update, context)

        # [Rest of your button handler cases remain the same, just add Markdown formatting where appropriate]

    except Exception as e:
        logger.error(f"Error in button handler: {str(e)}")
        await query.edit_message_text(
            "❌ An unexpected error occurred. Our team has been notified.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Contact Support", callback_data='support')],
                [InlineKeyboardButton("🔙 Back", callback_data='back')]
            ])
        )

# [Rest of your existing functions remain the same]

def main() -> None:
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("endchat", end_chat))
    application.add_handler(CommandHandler("vouch", vouch))
    application.add_handler(CommandHandler("addbalance", add_balance))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Callback and message handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    application.add_handler(MessageHandler(filters.PHOTO, handle_messages))
    
    # Start cleanup task
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(cleanup_pending_payments()),
        when=5  # Start after 5 seconds
    )
    
    application.run_polling()

if __name__ == '__main__':
    main()
