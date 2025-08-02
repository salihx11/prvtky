import logging
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

# ===== LOGGING SETUP =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== CONFIGURATION =====
BOT_TOKEN = '7939176482:AAEWQkAtjqTJ2JY5YRRN9XsUS8AWy3kKoJI'
ADMIN_ID = 1362321291
NOWPAYMENTS_API_KEY = 'BJMQ1ZZ-K8JMX4G-GY0EP0N-V210854'
KYC_PRICE = 20
WEBAPP_URL = "https://coinspark.pro/kyc/index.php"
VOUCH_CHANNEL_ID = -1002871277227
MAX_PAYMENT_CHECKS = 6  # Maximum payment check attempts
CHECK_INTERVAL = 120  # 2 minutes between payment checks
PAYMENT_EXPIRY = 3600  # 1 hour payment expiry time
SUPPORT_CHAT_ID = "@YourSupportBot"
LOGO_URL = "https://i.ibb.co/rRzxDkJ/logo.png"  # Fixed URL format

# ===== PAYMENT CONFIGURATION =====
SUPPORTED_CRYPTOS = {
    'btc': {'name': 'Bitcoin', 'min_amount': 0.0005, 'fee': 0.0001},
    'eth': {'name': 'Ethereum', 'min_amount': 0.01, 'fee': 0.005},
    'usdt': {'name': 'Tether (TRC20)', 'min_amount': 20, 'fee': 1},
    'usdc': {'name': 'USD Coin', 'min_amount': 20, 'fee': 1},
    'xmr': {'name': 'Monero', 'min_amount': 0.1, 'fee': 0.01},
    'ton': {'name': 'Toncoin', 'min_amount': 10, 'fee': 0.5},
    'sol': {'name': 'Solana', 'min_amount': 0.5, 'fee': 0.05},
    'trx': {'name': 'TRON', 'min_amount': 200, 'fee': 10},
    'dai': {'name': 'Dai', 'min_amount': 20, 'fee': 1},
    'dash': {'name': 'Dash', 'min_amount': 0.1, 'fee': 0.01},
    'ltc': {'name': 'Litecoin', 'min_amount': 0.1, 'fee': 0.01},
    'bch': {'name': 'Bitcoin Cash', 'min_amount': 0.01, 'fee': 0.001},
    'xrp': {'name': 'Ripple', 'min_amount': 20, 'fee': 1}
}

# ===== THEME & UI =====
THEME = {
    "primary": "🔵",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "info": "ℹ️",
    "money": "💰",
    "kyc": "🆔",
    "support": "🆘",
    "back": "🔙",
    "refresh": "🔄",
    "crypto": "🪙",
    "time": "⏳",
    "shield": "🛡️",
    "verified": "✅",
    "pending": "🔄"
}

# ===== GLOBAL STATE =====
user_balances = {}
payment_history = {}
pending_orders = {}
active_chats = {}
broadcast_messages = []
payment_timers = {}
vouches = {}

# ===== UTILITY FUNCTIONS =====
def admin_only(func):
    """Decorator to restrict commands to admin only"""
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text(
                f"{THEME['error']} Access Denied\n\n"
                "This command is restricted to administrators only.",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
            return
        return await func(update, context)
    return wrapped

def back_button():
    """Helper function to create a back button"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{THEME['back']} Back", callback_data="back")]])

async def send_photo_with_caption(context, chat_id, photo_url, caption, reply_markup=None):
    """Helper to send photo with caption"""
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_url,
            caption=caption,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending photo: {str(e)}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

# ===== PAYMENT FUNCTIONS =====
async def create_payment_invoice(user_id: int, crypto_code: str) -> tuple:
    """Create a payment invoice with NowPayments API"""
    try:
        crypto_code = crypto_code.lower()
        if crypto_code not in SUPPORTED_CRYPTOS:
            return None, f"{THEME['error']} Unsupported Currency\n\nThis cryptocurrency is not currently supported."

        url = "https://api.nowpayments.io/v1/invoice"
        headers = {
            "x-api-key": NOWPAYMENTS_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "price_amount": KYC_PRICE,
            "price_currency": "usd",
            "pay_currency": crypto_code,
            "ipn_callback_url": f"{WEBAPP_URL}/callback",
            "order_id": f"KYC_{user_id}_{datetime.datetime.now().timestamp()}",
            "order_description": "Fragment KYC Verification",
            "success_url": f"https://t.me/YourKycBot?start=success_{user_id}",
            "cancel_url": f"https://t.me/YourKycBot?start=cancel_{user_id}",
            "is_fixed_rate": True,
            "is_fee_paid_by_user": True
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if 'invoice_url' not in data:
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Invoice creation error: {error_msg}")
            
            if "not supported" in error_msg.lower():
                return None, f"{THEME['error']} Unsupported Currency\n\n{crypto_code.upper()} payments are temporarily unavailable."
            elif "minimum amount" in error_msg.lower():
                min_amount = SUPPORTED_CRYPTOS[crypto_code]['min_amount']
                return None, f"{THEME['error']} Minimum Amount\n\nThe minimum payment for {crypto_code.upper()} is {min_amount}."
                
            return None, f"{THEME['error']} Payment Failed\n\nWe couldn't create your payment request. Please try another method."
            
        return data, None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Payment API request failed: {str(e)}")
        return None, f"{THEME['error']} Service Unavailable\n\nPayment processor is currently unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, f"{THEME['error']} System Error\n\nAn unexpected error occurred. Our team has been notified."

async def check_payment_status(payment_id: str) -> tuple:
    """Check payment status with NowPayments API"""
    try:
        url = f"https://api.nowpayments.io/v1/payment/{payment_id}"
        headers = {"x-api-key": NOWPAYMENTS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Payment check failed: {response.status_code} - {response.text}")
            return False, None
            
        data = response.json()
        logger.info(f"Payment check response: {data}")
        
        status = data.get("payment_status", "").lower()
        if status in ['finished', 'confirmed', 'completed', 'paid']:
            return True, data
            
        pay_amount = float(data.get("pay_amount", 0))
        actually_paid = float(data.get("actually_paid", 0))
        if actually_paid >= pay_amount * 0.95:
            return True, data
            
        return False, data
        
    except Exception as e:
        logger.error(f"Payment check exception: {str(e)}")
        return False, None

async def start_payment_timer(user_id: int, payment_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Start a timer to check payment status periodically"""
    payment_timers[payment_id] = {
        'user_id': user_id,
        'attempts': 0,
        'start_time': datetime.datetime.now(),
        'last_check': datetime.datetime.now()
    }
    
    await asyncio.sleep(60)
    await _check_payment_periodically(payment_id, context)

async def _check_payment_periodically(payment_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Internal function for periodic payment checking"""
    if payment_id not in payment_timers:
        return
        
    timer = payment_timers[payment_id]
    user_id = timer['user_id']
    
    if (datetime.datetime.now() - timer['start_time']).seconds > PAYMENT_EXPIRY:
        logger.info(f"Payment {payment_id} expired")
        del payment_timers[payment_id]
        
        if payment_id in payment_history:
            payment_history[payment_id]['status'] = 'expired'
            
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"{THEME['error']} Payment Expired\n\n"
                     "Your payment session has expired. Please initiate a new payment if you still wish to proceed.",
                reply_markup=back_button()
            )
        except Exception as e:
            logger.error(f"Could not notify user {user_id} of expired payment: {str(e)}")
        return
    
    if timer['attempts'] >= MAX_PAYMENT_CHECKS:
        logger.info(f"Max payment checks reached for {payment_id}")
        del payment_timers[payment_id]
        return
    
    is_paid, payment_data = await check_payment_status(payment_id)
    
    if is_paid:
        del payment_timers[payment_id]
        user_balances[user_id] = user_balances.get(user_id, 0) + KYC_PRICE
        payment_history[payment_id]['status'] = 'completed'
        
        try:
            await send_photo_with_caption(
                context,
                user_id,
                LOGO_URL,
                f"{THEME['success']} *Payment Confirmed!*\n\n"
                f"• Amount: ${KYC_PRICE}\n"
                f"• Transaction: `{payment_data.get('payin_hash', 'N/A')}`\n"
                f"• New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                "You can now proceed with your KYC order.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                    [InlineKeyboardButton(f"{THEME['back']} Main Menu", callback_data='back')]
                ])
            )
        except Exception as e:
            logger.error(f"Could not notify user {user_id} of successful payment: {str(e)}")
    else:
        timer['attempts'] += 1
        timer['last_check'] = datetime.datetime.now()
        await asyncio.sleep(CHECK_INTERVAL)
        await _check_payment_periodically(payment_id, context)

# ===== COMMAND HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    try:
        user = update.effective_user
        user_id = user.id
        
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
            
            await send_photo_with_caption(
                context,
                user_id,
                LOGO_URL,
                f"{THEME['success']} *Payment Successful!*\n\n"
                f"• Amount: *${KYC_PRICE}* added to your balance\n"
                f"• New Balance: *${user_balances[user_id]:.2f}*\n\n"
                "What would you like to do next?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                    [InlineKeyboardButton(f"{THEME['money']} View Balance", callback_data='balance')],
                    [InlineKeyboardButton(f"{THEME['info']} History", callback_data='history')],
                    [InlineKeyboardButton(f"{THEME['back']} Main Menu", callback_data='back')]
                ])
            )
            return
        
        welcome_message = f"""
{THEME['shield']} *Welcome to Fragment KYC Verification* {THEME['shield']}

🔐 *Secure & Affordable KYC Service*
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
Reviews: [View Testimonials](https://t.me/YourReviewsChannel)
Support: @YourSupportBot
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{THEME['money']} Deposit Funds", callback_data='deposit')],
            [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
            [InlineKeyboardButton(f"{THEME['info']} Transaction History", callback_data='history')],
            [InlineKeyboardButton(f"{THEME['support']} Support", callback_data='support')]
        ])
        
        await send_photo_with_caption(
            context,
            user_id,
            LOGO_URL,
            welcome_message,
            reply_markup=keyboard
        )
    
    except Exception as e:
        logger.error(f"Error in start handler: {str(e)}")
        if update.message:
            await update.message.reply_text(
                f"{THEME['error']} An error occurred. Please try again.",
                reply_markup=back_button()
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                f"{THEME['error']} An error occurred. Please try again.",
                reply_markup=back_button()
            )

@admin_only
async def addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to add balance to a user"""
    try:
        args = context.args
        
        if len(args) < 2:
            await update.message.reply_text(
                f"{THEME['error']} Usage: /addbalance <user_id> <amount> [currency=USD]",
                parse_mode='Markdown'
            )
            return
        
        user_id = int(args[0])
        amount = float(args[1])
        currency = args[2].upper() if len(args) > 2 else "USD"
        
        if amount <= 0:
            await update.message.reply_text(
                f"{THEME['error']} Amount must be positive",
                parse_mode='Markdown'
            )
            return
            
        user_balances[user_id] = user_balances.get(user_id, 0) + amount
        
        payment_id = f"admin_{datetime.datetime.now().timestamp()}"
        payment_history[payment_id] = {
            'user_id': user_id,
            'amount': amount,
            'currency': currency,
            'status': 'completed',
            'timestamp': datetime.datetime.now().isoformat(),
            'admin_id': update.effective_user.id
        }
        
        await update.message.reply_text(
            f"{THEME['success']} Added *{amount} {currency}* to user *{user_id}*\n"
            f"New balance: *{user_balances[user_id]:.2f} USD*",
            parse_mode='Markdown'
        )
        
        try:
            await send_photo_with_caption(
                context,
                user_id,
                LOGO_URL,
                f"{THEME['success']} *Admin added {amount} {currency} to your balance*\n"
                f"New balance: *{user_balances[user_id]:.2f} USD*",
                reply_markup=back_button()
            )
        except Exception as e:
            logger.warning(f"Could not notify user {user_id}: {str(e)}")
            
    except ValueError:
        await update.message.reply_text(
            f"{THEME['error']} Invalid arguments. Usage: /addbalance <user_id> <amount> [currency]",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in addbalance: {str(e)}")
        await update.message.reply_text(
            f"{THEME['error']} An error occurred. Please check your input.",
            reply_markup=back_button()
        )

# ===== PAYMENT HANDLERS =====
async def deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle deposit requests with perfectly aligned buttons"""
    try:
        query = update.callback_query
        await query.answer()
        
        message = f"""
{THEME['money']} *Deposit Funds* {THEME['money']}

🔹 *Service Price:* ${KYC_PRICE}
🔹 *Processing:* Instant
🔹 *Supported Cryptocurrencies:*

Choose your preferred payment method:
        """
        
        # Perfectly aligned 2x3 grid for main currencies
        keyboard = [
            [
                InlineKeyboardButton("Bitcoin", callback_data="pay_btc"),
                InlineKeyboardButton("Ethereum", callback_data="pay_eth")
            ],
            [
                InlineKeyboardButton("USDT (TRC20)", callback_data="pay_usdt"),
                InlineKeyboardButton("USDC", callback_data="pay_usdc")
            ],
            [
                InlineKeyboardButton("XRP", callback_data="pay_xrp"),
                InlineKeyboardButton("Toncoin", callback_data="pay_ton")
            ],
            [
                InlineKeyboardButton("More Options ➡️", callback_data="more_crypto_options"),
                InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')
            ]
        ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error in deposit handler: {str(e)}")
        await query.edit_message_text(
            text=f"{THEME['error']} An error occurred. Please try again.",
            reply_markup=back_button()
        )

async def more_crypto_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show additional cryptocurrency options with perfect button alignment"""
    try:
        query = update.callback_query
        await query.answer()
        
        message = f"""
{THEME['money']} *Additional Payment Options* {THEME['money']}

Select from our other supported cryptocurrencies:
        """
        
        # Perfect 2x3 grid for additional options
        keyboard = [
            [
                InlineKeyboardButton("Solana", callback_data="pay_sol"),
                InlineKeyboardButton("TRON", callback_data="pay_trx")
            ],
            [
                InlineKeyboardButton("Monero", callback_data="pay_xmr"),
                InlineKeyboardButton("Litecoin", callback_data="pay_ltc")
            ],
            [
                InlineKeyboardButton("Dash", callback_data="pay_dash"),
                InlineKeyboardButton("Bitcoin Cash", callback_data="pay_bch")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Main", callback_data="deposit"),
                InlineKeyboardButton(f"{THEME['back']} Main Menu", callback_data="back")
            ]
        ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error in more_crypto_options: {str(e)}")
        await query.edit_message_text(
            text=f"{THEME['error']} An error occurred. Please try again.",
            reply_markup=back_button()
        )

async def payment_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the payment flow with perfect button layout"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        crypto_code = query.data.split('_')[1].lower()
        
        if crypto_code not in SUPPORTED_CRYPTOS:
            await query.edit_message_text(
                text=f"{THEME['error']} Unsupported Currency\n\n"
                "This cryptocurrency is not currently supported.",
                reply_markup=back_button()
            )
            return
            
        crypto_name = SUPPORTED_CRYPTOS[crypto_code]['name']
        crypto_fee = SUPPORTED_CRYPTOS[crypto_code]['fee']
        
        await query.edit_message_text(
            text=f"{THEME['time']} Creating {crypto_name} payment invoice...",
            reply_markup=None
        )
        
        invoice_data, error_msg = await create_payment_invoice(user_id, crypto_code)
        
        if error_msg:
            await query.edit_message_text(
                text=error_msg,
                reply_markup=back_button()
            )
            return
            
        payment_id = invoice_data['id']
        invoice_url = invoice_data['invoice_url']
        expiry_time = (datetime.datetime.now() + datetime.timedelta(seconds=PAYMENT_EXPIRY)).strftime('%H:%M:%S UTC')
        
        payment_history[payment_id] = {
            'user_id': user_id,
            'amount': KYC_PRICE,
            'currency': crypto_code,
            'status': 'pending',
            'timestamp': datetime.datetime.now().isoformat(),
            'invoice_url': invoice_url,
            'expiry': expiry_time
        }
        
        asyncio.create_task(start_payment_timer(user_id, payment_id, context))
        
        message = f"""
{THEME['money']} *{crypto_name} Payment Instructions* {THEME['money']}

🔹 *Amount:* ${KYC_PRICE} USD
🔹 *Network Fee:* ~{crypto_fee} {crypto_code.upper()}
🔹 *Payment ID:* `{payment_id}`
🔹 *Expires at:* {expiry_time}

Please complete your payment within 1 hour.
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay Now", url=invoice_url)],
            [InlineKeyboardButton(f"{THEME['refresh']} Check Status", callback_data=f'check_{payment_id}')],
            [InlineKeyboardButton(f"{THEME['back']} Cancel", callback_data='deposit')]
        ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error in payment flow: {str(e)}")
        await query.edit_message_text(
            text=f"{THEME['error']} An error occurred. Please try again.",
            reply_markup=back_button()
        )

async def payment_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment status checks"""
    try:
        query = update.callback_query
        await query.answer()
        
        payment_id = query.data.split('_')[1]
        
        if payment_id not in payment_history:
            await query.answer("Payment not found. It may have expired.", show_alert=True)
            return
            
        await query.edit_message_text(
            text=f"{THEME['time']} Checking payment status...",
            reply_markup=None
        )
        
        is_paid, payment_data = await check_payment_status(payment_id)
        
        if is_paid:
            user_id = payment_history[payment_id]['user_id']
            user_balances[user_id] = user_balances.get(user_id, 0) + KYC_PRICE
            payment_history[payment_id]['status'] = 'completed'
            
            if payment_id in payment_timers:
                del payment_timers[payment_id]
            
            await send_photo_with_caption(
                context,
                user_id,
                LOGO_URL,
                f"{THEME['success']} *Payment Confirmed!*\n\n"
                f"• Amount: ${KYC_PRICE}\n"
                f"• Transaction: `{payment_data.get('payin_hash', 'N/A')}`\n"
                f"• New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                "You can now proceed with your KYC order.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                    [InlineKeyboardButton(f"{THEME['back']} Main Menu", callback_data='back')]
                ])
            )
        else:
            expiry_time = payment_history[payment_id].get('expiry', 'N/A')
            
            await query.edit_message_text(
                text=f"{THEME['info']} *Payment Status*\n\n"
                f"• Status: {THEME['pending']} PENDING\n"
                f"• Expires at: {expiry_time}\n\n"
                "Please check again in a few minutes.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['refresh']} Check Again", callback_data=f'check_{payment_id}')],
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='deposit')]
                ])
            )
            
    except Exception as e:
        logger.error(f"Error in payment status handler: {str(e)}")
        await query.edit_message_text(
            text=f"{THEME['error']} An error occurred. Please try again.",
            reply_markup=back_button()
        )

# ===== ORDER HANDLERS =====
async def order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle KYC order requests"""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        balance = user_balances.get(user_id, 0)
        
        if balance >= KYC_PRICE:
            user_balances[user_id] = balance - KYC_PRICE
            order_id = f"ORD_{user_id}_{datetime.datetime.now().timestamp()}"
            pending_orders[order_id] = {
                'user_id': user_id,
                'amount': KYC_PRICE,
                'status': 'pending',
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            await send_photo_with_caption(
                context,
                user_id,
                LOGO_URL,
                f"{THEME['success']} *KYC Order Placed!*\n\n"
                f"• Price: ${KYC_PRICE}\n"
                f"• New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                "Please provide your details to complete verification.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['support']} Provide Details", callback_data='chat_admin')],
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
                ])
            )
            
            admin_message = f"""
⚠️ *New KYC Order*

• User: {query.from_user.mention_markdown()}
• ID: `{user_id}`
• Order ID: `{order_id}`
• Balance: ${user_balances.get(user_id, 0):.2f}
            """
            
            await send_photo_with_caption(
                context,
                ADMIN_ID,
                LOGO_URL,
                admin_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['support']} Chat", callback_data=f"chat_{user_id}")],
                    [InlineKeyboardButton(f"{THEME['verified']} Complete", callback_data=f"done_{user_id}")]
                ])
            )
        else:
            await query.edit_message_text(
                text=f"{THEME['error']} *Insufficient Balance*\n\nYou need ${KYC_PRICE} for KYC verification.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['money']} Deposit Funds", callback_data='deposit')],
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
                ])
            )
    except Exception as e:
        logger.error(f"Error in order handler: {str(e)}")
        await query.edit_message_text(
            text=f"{THEME['error']} An error occurred. Please try again.",
            reply_markup=back_button()
        )

# ===== MAIN APPLICATION =====
async def post_init(application):
    """Run after bot initialization"""
    logger.info("Bot initialization complete")

async def post_stop(application):
    """Run before bot shutdown"""
    logger.info("Bot shutdown complete")

def main() -> None:
    """Start the bot"""
    application = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .post_init(post_init) \
        .post_stop(post_stop) \
        .build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addbalance", addbalance))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(start, pattern='^back$'))
    application.add_handler(CallbackQueryHandler(deposit_handler, pattern='^deposit$'))
    application.add_handler(CallbackQueryHandler(more_crypto_options, pattern='^more_crypto_options$'))
    application.add_handler(CallbackQueryHandler(payment_flow, pattern='^pay_'))
    application.add_handler(CallbackQueryHandler(payment_status_handler, pattern='^check_'))
    application.add_handler(CallbackQueryHandler(order_handler, pattern='^order$'))
    
    logger.info("Starting bot...")
    application.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()
