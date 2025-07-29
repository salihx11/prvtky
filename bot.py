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

# Constants - Replace with your actual credentials
BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
ADMIN_ID = YOUR_ADMIN_USER_ID  # Replace with your Telegram user ID
NOWPAYMENTS_API_KEY = 'YOUR_NOWPAYMENTS_API_KEY'
KYC_PRICE = 20  # Price for KYC verification in USD
WEBAPP_URL = "https://yourdomain.com/kyc"  # Your web application URL
VOUCH_CHANNEL_ID = -1000000000000  # Your channel ID for feedback
MAX_PAYMENT_CHECKS = 3  # Maximum payment check attempts
CHECK_COOLDOWN = 600  # 10 minutes cooldown between payment checks
SUPPORT_CHAT_ID = "@YourSupportBot"  # Your support bot username

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global state management (in production, use a database)
user_balances = {}
payment_history = {}
pending_orders = {}
active_chats = {}
broadcast_messages = []
payment_check_attempts = {}
vouches = {}

# Supported cryptocurrencies
POPULAR_CRYPTOS = ['btc', 'eth', 'usdt', 'usdc', 'xmr', 'ton', 'sol', 'trx']

# Theme configuration with improved emojis
THEME = {
    "primary": "🔵",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "info": "ℹ️",
    "money": "💰",
    "kyc": "🆔",
    "support": "🆘",
    "back": "🔙"
}

def admin_only(func):
    """Decorator to restrict commands to admin only"""
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text(
                f"{THEME['error']} ⚠️ Access Denied\n\n"
                "This command is restricted to administrators only.",
                parse_mode='Markdown'
            )
            return
        return await func(update, context)
    return wrapped

def back_button():
    """Helper function to create a back button with improved emoji"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{THEME['back']} Back", callback_data="back")]])

async def create_invoice(user_id: int, coin_code: str):
    """
    Create a payment invoice with NowPayments API
    Returns tuple of (invoice_data, error_message)
    """
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
            "success_url": f"https://t.me/YourKycBot?start=success_{user_id}",
            "cancel_url": f"https://t.me/YourKycBot?start=cancel_{user_id}"
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'invoice_url' not in data:
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Invoice creation error: {error_msg}")
            if "Currency" in error_msg and "not supported" in error_msg:
                return None, f"{THEME['error']} Unsupported Currency\n\nThis cryptocurrency is not currently supported for payments. Please try another payment method."
            return None, f"{THEME['error']} Payment Failed\n\nWe couldn't create your payment request. Please try another method."
            
        return data, None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Invoice creation request failed: {str(e)}")
        return None, f"{THEME['error']} Service Unavailable\n\nOur payment processor is currently unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, f"{THEME['error']} System Error\n\nAn unexpected error occurred. Our team has been notified. Please try again later."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /start command and show main menu
    """
    try:
        if update.message and update.message.text.startswith('/start success_'):
            # Handle successful payment callback
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
                f"{THEME['success']} *Payment Successful!*\n\n"
                f"• Amount: *${KYC_PRICE}* has been added to your balance\n"
                f"• New Balance: *${user_balances[user_id]:.2f}*\n\n"
                "What would you like to do next?",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                    [InlineKeyboardButton(f"{THEME['money']} View Balance", callback_data='balance')],
                    [InlineKeyboardButton(f"{THEME['info']} History", callback_data='history')],
                    [InlineKeyboardButton(f"{THEME['back']} Main Menu", callback_data='back')]
                ])
            )
            return
        
        # Main menu keyboard
        keyboard = [
            [InlineKeyboardButton(f"{THEME['money']} Balance", callback_data='balance'),
             InlineKeyboardButton(f"{THEME['money']} Deposit", callback_data='deposit')],
            [InlineKeyboardButton(f"{THEME['kyc']} Order KYC Verification", callback_data='order')],
            [InlineKeyboardButton(f"{THEME['info']} Transaction History", callback_data='history')],
            [InlineKeyboardButton(f"{THEME['support']} Support", callback_data='support'),
             InlineKeyboardButton("⭐ Leave Feedback", callback_data='vouch')]
        ]
        
        welcome_message = f"""
{THEME['primary']} *Welcome to Fragment KYC Bot* {THEME['primary']}

🔐 *Secure & Affordable KYC Verification*
✅ Trusted by 1000+ users worldwide
⚡ Fast processing within minutes

💼 *Services:*
• Fragment.com KYC Verification
• Personal/Corporate accounts
• 100% success guarantee

📌 *How it works:*
1. Deposit funds (${KYC_PRICE} per verification)
2. Submit your details securely
3. Get verified within minutes

📢 *Community:*
Reviews: https://t.me/YourReviewsChannel
Support: @YourSupportBot
        """
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Error in start handler: {str(e)}")
        error_message = f"""
{THEME['error']} *System Error*

We encountered an issue while processing your request. Our team has been notified.

Please try again later or contact support if the problem persists.
        """
        await update.message.reply_text(
            error_message,
            parse_mode='Markdown',
            reply_markup=back_button()
        )

# [Rest of your handlers with similar error handling improvements...]

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enhanced error handler with detailed logging and user feedback"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    error_details = f"""
{THEME['error']} *System Error Details*

• Error: `{context.error.__class__.__name__}`
• Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Update: {update.to_dict() if update else 'None'}
"""
    logger.error(error_details)
    
    if update and update.effective_message:
        user_message = f"""
{THEME['error']} *An Error Occurred*

We've encountered an unexpected error. Our technical team has been notified.

Please try your action again. If the problem persists, contact our support team.

{THEME['back']} You can return to the main menu below.
        """
        await update.effective_message.reply_text(
            user_message,
            parse_mode='Markdown',
            reply_markup=back_button()
        )

def main() -> None:
    """Start the bot with enhanced configuration"""
    application = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .post_init(lambda app: logger.info("Bot initialization complete")) \
        .post_stop(lambda app: logger.info("Bot shutdown complete")) \
        .build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("endchat", end_chat))
    application.add_handler(CommandHandler("vouch", vouch_command))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("confirmbroadcast", confirm_broadcast))
    application.add_handler(CommandHandler("cancelbroadcast", cancel_broadcast))
    application.add_handler(CommandHandler("addbalance", addbalance))
    
    # Callback and message handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    application.add_handler(MessageHandler(filters.PHOTO, handle_messages))
    
    # Start cleanup task
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(cleanup_pending_payments()),
        when=5
    )
    
    logger.info("Bot is starting with enhanced configuration...")
    application.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
