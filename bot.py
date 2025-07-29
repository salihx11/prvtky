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

# ===== CONFIGURATION =====
BOT_TOKEN = '7939176482:AAEWQkAtjqTJ2JY5YRRN9XsUS8AWy3kKoJI'
ADMIN_ID = 1362321291
NOWPAYMENTS_API_KEY = 'BJMQ1ZZ-K8JMX4G-GY0EP0N-V210854'
KYC_PRICE = 20
WEBAPP_URL = "https://coinspark.pro/kyc/index.php"
VOUCH_CHANNEL_ID = -1002871277227
MAX_PAYMENT_CHECKS = 3
CHECK_COOLDOWN = 600
SUPPORT_CHAT_ID = "@Fragkycsupportbot"

# ===== LOGGING SETUP =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== GLOBAL STATE =====
user_balances = {}
payment_history = {}
pending_orders = {}
active_chats = {}
broadcast_messages = []
payment_check_attempts = {}
vouches = {}

# ===== CONSTANTS =====
POPULAR_CRYPTOS = ['btc', 'eth', 'usdt', 'usdc', 'xmr', 'ton', 'sol', 'trx']

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
    "refresh": "🔄"
}

# ===== UTILITY FUNCTIONS =====
def admin_only(func):
    """Decorator to restrict commands to admin only"""
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text(
                f"{THEME['error']} ⚠️ Access Denied\n\n"
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

def create_menu_keyboard():
    """Create the main menu keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{THEME['money']} Balance", callback_data='balance'),
         InlineKeyboardButton(f"{THEME['money']} Deposit", callback_data='deposit')],
        [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
        [InlineKeyboardButton(f"{THEME['info']} History", callback_data='history')],
        [InlineKeyboardButton(f"{THEME['support']} Support", callback_data='support'),
         InlineKeyboardButton("⭐ Leave Feedback", callback_data='vouch')]
    ])

# ===== CORE FUNCTIONALITY =====
async def create_invoice(user_id: int, coin_code: str):
    """Create a payment invoice with NowPayments API"""
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
                return None, f"{THEME['error']} Unsupported Currency\n\nThis cryptocurrency is not currently supported for payments."
            return None, f"{THEME['error']} Payment Failed\n\nWe couldn't create your payment request. Please try again."
            
        return data, None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Invoice creation request failed: {str(e)}")
        return None, f"{THEME['error']} Service Unavailable\n\nPayment processor is currently unavailable."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, f"{THEME['error']} System Error\n\nAn unexpected error occurred. Please try again."

async def check_payment_status(payment_id: str):
    """Check payment status with NowPayments API"""
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

# ===== COMMAND HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    try:
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
                f"{THEME['success']} *Payment Successful!*\n\n"
                f"• Amount: *${KYC_PRICE}* added to your balance\n"
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
        
        if update.message:
            await update.message.reply_text(
                welcome_message,
                parse_mode='Markdown',
                reply_markup=create_menu_keyboard()
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                welcome_message,
                parse_mode='Markdown',
                reply_markup=create_menu_keyboard()
            )
    
    except Exception as e:
        logger.error(f"Error in start handler: {str(e)}")
        await handle_error(update, context, e)

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
            await context.bot.send_message(
                chat_id=user_id,
                text=f"{THEME['success']} *Admin added {amount} {currency} to your balance*\n"
                     f"New balance: *{user_balances[user_id]:.2f} USD*",
                parse_mode='Markdown'
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
        await handle_error(update, context, e)

# ===== CALLBACK HANDLERS =====
async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle support requests"""
    try:
        query = update.callback_query
        await query.answer()
        
        support_message = f"""
{THEME['support']} *Support Center* {THEME['support']}

Need help? Here are your options:

1. *Live Chat* - Connect directly with our support team
2. *FAQ* - Common questions and solutions
3. *Status* - Check system status

For immediate assistance, please use the live chat option below.
        """
        
        await query.edit_message_text(
            support_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['support']} Live Chat", callback_data='chat_admin')],
                [InlineKeyboardButton("📚 FAQ", url="https://fragment.com/faq")],
                [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
            ])
        )
    except Exception as e:
        logger.error(f"Error in support handler: {str(e)}")
        await handle_error(update, context, e)

async def vouch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user feedback/vouches"""
    try:
        query = update.callback_query
        await query.answer()
        
        vouch_message = f"""
⭐ *Share Your Experience* ⭐

We value your feedback! Please share your experience with our KYC service.

Example:
`/vouch Excellent service! Got verified in 10 minutes.`
        """
        
        await query.edit_message_text(
            vouch_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👀 View Testimonials", url=f"https://t.me/YourReviewsChannel")],
                [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
            ])
        )
    except Exception as e:
        logger.error(f"Error in vouch handler: {str(e)}")
        await handle_error(update, context, e)

async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user balance"""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        balance = user_balances.get(user_id, 0)
        
        balance_message = f"""
{THEME['money']} *Account Balance* {THEME['money']}

💰 *Available Balance:* ${balance:.2f}
📋 *KYC Service Price:* ${KYC_PRICE}

"""
        
        if balance >= KYC_PRICE:
            balance_message += f"{THEME['success']} You have sufficient balance for KYC verification!"
        else:
            balance_message += f"{THEME['warning']} You need ${KYC_PRICE-balance:.2f} more for KYC verification."
        
        await query.edit_message_text(
            balance_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['money']} Deposit Funds", callback_data='deposit')],
                [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
            ])
        )
    except Exception as e:
        logger.error(f"Error in balance handler: {str(e)}")
        await handle_error(update, context, e)

async def deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle deposit requests"""
    try:
        query = update.callback_query
        await query.answer()
        
        deposit_message = f"""
{THEME['money']} *Deposit Funds* {THEME['money']}

Choose your preferred payment method:

🔹 *Minimum Deposit:* ${KYC_PRICE}
🔹 *Service Fee:* 0%
🔹 *Instant Processing*
        """
        
        buttons = []
        row = []
        for i, crypto in enumerate(POPULAR_CRYPTOS):
            row.append(InlineKeyboardButton(crypto.upper(), callback_data=f'pay_{crypto}'))
            if (i + 1) % 3 == 0:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')])
        
        await query.edit_message_text(
            deposit_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error in deposit handler: {str(e)}")
        await handle_error(update, context, e)

async def payment_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment flow"""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        coin = query.data.split("_")[1].lower()
        
        invoice_data, error_msg = await create_invoice(user_id, coin)
        
        if error_msg:
            await query.edit_message_text(
                error_msg,
                parse_mode='Markdown',
                reply_markup=back_button()
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
        
        payment_check_attempts[user_id] = 0
        
        payment_message = f"""
{THEME['money']} *Payment Instructions* {THEME['money']}

🔹 *Amount:* ${KYC_PRICE} USD
🔹 *Currency:* {coin.upper()}
🔹 *Payment ID:* `{payment_id}`
🔹 *Status:* Waiting for payment

Please complete your payment within 15 minutes.
        """
        
        await query.edit_message_text(
            payment_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Pay Now", url=invoice_data['invoice_url'])],
                [InlineKeyboardButton(f"{THEME['refresh']} Check Payment", callback_data=f'check_{payment_id}')],
                [InlineKeyboardButton(f"{THEME['back']} Cancel", callback_data='deposit')]
            ])
        )
    except Exception as e:
        logger.error(f"Error in payment flow: {str(e)}")
        await handle_error(update, context, e)

async def payment_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment status checks"""
    try:
        query = update.callback_query
        await query.answer()
        payment_id = query.data.split("_")[1]
        
        if payment_id not in payment_history:
            await query.answer("Payment record not found", show_alert=True)
            return
        
        user_id = query.from_user.id
        payment_check_attempts[user_id] = payment_check_attempts.get(user_id, 0) + 1
        
        if payment_check_attempts[user_id] > MAX_PAYMENT_CHECKS:
            await query.answer(
                f"You've exceeded verification attempts. Please wait {CHECK_COOLDOWN//60} minutes.",
                show_alert=True
            )
            return
        
        is_paid, payment_data = await check_payment_status(payment_id)
        
        if is_paid:
            user_balances[user_id] = user_balances.get(user_id, 0) + KYC_PRICE
            payment_history[payment_id]['status'] = 'completed'
            payment_history[payment_id]['tx_hash'] = payment_data.get('payin_hash', 'N/A')
            payment_check_attempts[user_id] = 0
            
            success_message = f"""
{THEME['success']} *Payment Confirmed!* {THEME['success']}

• Amount: ${KYC_PRICE}
• Transaction: {payment_data.get('payin_hash', 'N/A')}
• New Balance: ${user_balances.get(user_id, 0):.2f}

Thank you for your payment!
            """
            
            await query.edit_message_text(
                success_message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                    [InlineKeyboardButton(f"{THEME['info']} History", callback_data='history')],
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
                ])
            )
            
            receipt_message = f"""
📋 *Payment Receipt*

• ID: `{payment_id}`
• Amount: ${KYC_PRICE}
• Currency: {payment_history[payment_id]['currency'].upper()}
• Status: Completed
• Hash: {payment_data.get('payin_hash', 'N/A')}
• Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            await context.bot.send_message(
                chat_id=user_id,
                text=receipt_message,
                parse_mode='Markdown'
            )
        else:
            remaining_attempts = MAX_PAYMENT_CHECKS - payment_check_attempts[user_id]
            status_message = "⌛ Payment still processing"
            if payment_data:
                status_message = f"⌛ Current status: {payment_data.get('payment_status', 'pending').upper()}"
            
            status_update = f"""
{THEME['info']} *Payment Status* {THEME['info']}

• ID: `{payment_id}`
• Amount: ${KYC_PRICE}
• Currency: {payment_history[payment_id]['currency'].upper()}
• Status: {payment_data.get('payment_status', 'PENDING').upper() if payment_data else 'PENDING'}
• Attempts left: {remaining_attempts}

ℹ️ You can check again in a few minutes
            """
            
            await query.edit_message_text(
                status_update,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['refresh']} Check Again", callback_data=f'check_{payment_id}')],
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='deposit')]
                ])
            )
            
            await query.answer(
                f"{status_message}\nAttempts remaining: {remaining_attempts}",
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Error in payment status handler: {str(e)}")
        await handle_error(update, context, e)

async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show transaction history"""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        user_history = [
            payment for payment in payment_history.values() 
            if payment['user_id'] == user_id
        ]
        
        if not user_history:
            await query.edit_message_text(
                f"{THEME['info']} No payment history found",
                reply_markup=back_button()
            )
            return
        
        history_text = f"""
{THEME['info']} *Transaction History* {THEME['info']}

📋 Last 10 transactions:
"""
        for i, payment in enumerate(user_history[-10:], 1):
            status_emoji = THEME['success'] if payment['status'] == 'completed' else THEME['warning']
            history_text += (
                f"\n{i}. {payment['timestamp'].split('T')[0]} - "
                f"${payment['amount']} {payment['currency'].upper()} - "
                f"{status_emoji} {payment['status'].capitalize()}"
            )
        
        await query.edit_message_text(
            history_text,
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    except Exception as e:
        logger.error(f"Error in history handler: {str(e)}")
        await handle_error(update, context, e)

async def order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle KYC orders"""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        username = query.from_user.username or str(user_id)
        balance = user_balances.get(user_id, 0)
        
        if balance >= KYC_PRICE:
            user_balances[user_id] = balance - KYC_PRICE
            pending_orders[user_id] = {
                'username': username,
                'timestamp': datetime.datetime.now().isoformat(),
                'status': 'pending'
            }
            
            order_message = f"""
{THEME['success']} *KYC Order Placed!* {THEME['success']}

• Price: ${KYC_PRICE}
• New Balance: ${user_balances.get(user_id, 0):.2f}

Please provide your details to complete verification.
            """
            
            await query.edit_message_text(
                order_message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['support']} Provide Details", callback_data='chat_admin')],
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
                ])
            )
            
            admin_message = f"""
⚠️ *New KYC Order*

• User: @{username}
• ID: {user_id}
• Balance: ${user_balances.get(user_id, 0):.2f}
            """
            
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['support']} Chat", callback_data=f"chat_{user_id}")],
                    [InlineKeyboardButton(f"{THEME['success']} Complete", callback_data=f"done_{user_id}")]
                ])
            )
        else:
            await query.edit_message_text(
                f"{THEME['error']} *Insufficient Balance*\n\nYou need ${KYC_PRICE} for KYC verification.",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
    except Exception as e:
        logger.error(f"Error in order handler: {str(e)}")
        await handle_error(update, context, e)

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chat between users and admin"""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        username = query.from_user.username or str(user_id)
        
        if query.data == "chat_admin":
            active_chats[user_id] = ADMIN_ID
            welcome_message = f"""
{THEME['support']} *Support Chat* {THEME['support']}

To complete verification, please provide:
1. Telegram phone number
2. Email address
3. Preferred username

We'll guide you through the process.
            """
            
            await query.edit_message_text(
                welcome_message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['back']} Back", callback_data='back')]
                ])
            )
            
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💬 User @{username} ({user_id}) started a chat",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['support']} Reply", callback_data=f"chat_{user_id}")]
                ])
            )
        elif query.data.startswith("chat_"):
            if query.from_user.id != ADMIN_ID:
                return
                
            target_user_id = int(query.data.split("_")[1])
            active_chats[target_user_id] = ADMIN_ID
            
            await query.edit_message_text(
                f"{THEME['support']} Chatting with user {target_user_id}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{THEME['success']} Complete Order", callback_data=f"done_{target_user_id}")],
                    [InlineKeyboardButton(f"{THEME['error']} End Chat", callback_data=f"endchat_{target_user_id}")]
                ])
            )
            
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{THEME['support']} Admin is now chatting with you. Please send your details:"
            )
    except Exception as e:
        logger.error(f"Error in chat handler: {str(e)}")
        await handle_error(update, context, e)

async def complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark an order as complete"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            return
            
        target_user_id = int(query.data.split("_")[1])
        if target_user_id in pending_orders:
            pending_orders[target_user_id]['status'] = 'completed'
        
        if target_user_id in active_chats:
            del active_chats[target_user_id]
        
        await query.edit_message_text(f"{THEME['success']} Order for {target_user_id} completed")
        
        completion_message = f"""
{THEME['success']} *KYC Verification Complete!* {THEME['success']}

Thank you for using our service! Your account has been successfully verified.

⭐ Please consider leaving feedback with /vouch command.
        """
        
        await context.bot.send_message(
            chat_id=target_user_id,
            text=completion_message,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in complete_order: {str(e)}")
        await handle_error(update, context, e)

async def vouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /vouch command for user feedback"""
    try:
        user = update.effective_user
        args = context.args

        if not args:
            await update.message.reply_text(
                f"{THEME['info']} Please include your feedback text.\nExample:\n`/vouch Excellent service! Verified in 10 minutes.`",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
            return

        vouch_text = " ".join(args)
        vouches[user.id] = {
            "text": vouch_text,
            "username": user.username or f"user_{user.id}",
            "timestamp": datetime.datetime.now().isoformat()
        }

        message = f"""
⭐ *New Feedback for Fragment KYC*

✉️ {vouch_text}

#Feedback #KYC #{user.username or user.id}
        """

        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=f"Sent by: @{vouches[user.id]['username']}",
                url=f"tg://user?id={user.id}"
            )
        ]])

        sent = await context.bot.send_message(
            chat_id=VOUCH_CHANNEL_ID,
            text=message,
            reply_markup=buttons,
            parse_mode='Markdown'
        )

        await update.message.reply_text(
            f"{THEME['success']} Thank you for your feedback!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👀 View Post", url=f"https://t.me/c/{str(VOUCH_CHANNEL_ID)[4:]}/{sent.message_id}")
            ]])
        )
    except Exception as e:
        logger.error(f"Error in vouch command: {str(e)}")
        await handle_error(update, context, e)

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to broadcast a message"""
    try:
        if not context.args:
            await update.message.reply_text(
                f"{THEME['error']} Usage: /broadcast <message>",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
            return
        
        message = " ".join(context.args)
        broadcast_messages.append(message)
        
        await update.message.reply_text(
            f"{THEME['info']} *Broadcast Preview*\n\n{message}\n\n"
            f"Send /confirmbroadcast to send or /cancelbroadcast to cancel",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['success']} Confirm", callback_data="confirm_broadcast")],
                [InlineKeyboardButton(f"{THEME['error']} Cancel", callback_data="cancel_broadcast")]
            ])
        )
    except Exception as e:
        logger.error(f"Error in broadcast: {str(e)}")
        await handle_error(update, context, e)

@admin_only
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and send broadcast message"""
    try:
        if not broadcast_messages:
            await update.message.reply_text(
                f"{THEME['error']} No broadcast message pending",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
            return
        
        message = broadcast_messages[-1]
        sent_count = 0
        failed_count = 0
        
        user_ids = set()
        user_ids.update(user_balances.keys())
        user_ids.update(payment_history.keys())
        user_ids.update(pending_orders.keys())
        
        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 *Announcement*\n\n{message}",
                    parse_mode='Markdown'
                )
                sent_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.warning(f"Failed to send to {user_id}: {str(e)}")
                failed_count += 1
        
        broadcast_messages.clear()
        await update.message.reply_text(
            f"{THEME['success']} Sent to {sent_count} users. {failed_count} failed.",
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    except Exception as e:
        logger.error(f"Error in confirm_broadcast: {str(e)}")
        await handle_error(update, context, e)

@admin_only
async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel pending broadcast"""
    try:
        if not broadcast_messages:
            await update.message.reply_text(
                f"{THEME['error']} No broadcast message pending",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
            return
        
        broadcast_messages.clear()
        await update.message.reply_text(
            f"{THEME['success']} Broadcast cancelled",
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    except Exception as e:
        logger.error(f"Error in cancel_broadcast: {str(e)}")
        await handle_error(update, context, e)

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /endchat command"""
    try:
        if update.message.from_user.id != ADMIN_ID:
            return
        
        target_user_id = None
        for user_id, admin_id in active_chats.items():
            if admin_id == update.message.from_user.id:
                target_user_id = user_id
                break
        
        if target_user_id:
            del active_chats[target_user_id]
            await update.message.reply_text(
                f"{THEME['success']} Ended chat with {target_user_id}",
                reply_markup=back_button()
            )
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{THEME['info']} Admin has ended the chat"
            )
    except Exception as e:
        logger.error(f"Error in end_chat: {str(e)}")
        await handle_error(update, context, e)

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    try:
        user_id = update.message.from_user.id
        
        # Admin messages to user
        if user_id == ADMIN_ID:
            for target_id, admin_id in active_chats.items():
                if admin_id == user_id:
                    try:
                        if update.message.text:
                            await context.bot.send_message(
                                chat_id=target_id,
                                text=f"👨‍💼 Admin: {update.message.text}"
                            )
                        elif update.message.photo:
                            await context.bot.send_photo(
                                chat_id=target_id,
                                photo=update.message.photo[-1].file_id,
                                caption=f"👨‍💼 Admin: {update.message.caption or ''}"
                            )
                    except Exception as e:
                        logger.error(f"Error forwarding admin message: {e}")
                    return
        
        # User messages to admin
        elif user_id in active_chats:
            admin_id = active_chats[user_id]
            username = update.message.from_user.username or str(user_id)
            
            try:
                if update.message.text:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"👤 User @{username}: {update.message.text}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💬 Reply", callback_data=f"chat_{user_id}")]
                        ])
                    )
                elif update.message.photo:
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=update.message.photo[-1].file_id,
                        caption=f"👤 User @{username}: {update.message.caption or ''}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💬 Reply", callback_data=f"chat_{user_id}")]
                        ])
                    )
            except Exception as e:
                logger.error(f"Error forwarding user message: {e}")
    except Exception as e:
        logger.error(f"Error in handle_messages: {str(e)}")
        await handle_error(update, context, e)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "balance":
            await balance_handler(update, context)
        elif query.data == "deposit":
            await deposit_handler(update, context)
        elif query.data.startswith("pay_"):
            await payment_flow(update, context)
        elif query.data.startswith("check_"):
            await payment_status_handler(update, context)
        elif query.data == "history":
            await history_handler(update, context)
        elif query.data == "order":
            await order_handler(update, context)
        elif query.data == "chat_admin" or query.data.startswith("chat_"):
            await chat_handler(update, context)
        elif query.data.startswith("done_"):
            await complete_order(update, context)
        elif query.data == "support":
            await support_handler(update, context)
        elif query.data == "vouch":
            await vouch_handler(update, context)
        elif query.data == "back":
            await start(update, context)
        elif query.data.startswith("endchat_"):
            target_user_id = int(query.data.split("_")[1])
            if target_user_id in active_chats:
                del active_chats[target_user_id]
            await query.edit_message_text(f"{THEME['success']} Chat ended with {target_user_id}")
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{THEME['info']} Admin has ended the chat"
            )
        elif query.data == "confirm_broadcast":
            await confirm_broadcast(update, context)
        elif query.data == "cancel_broadcast":
            await cancel_broadcast(update, context)
            
    except Exception as e:
        logger.error(f"Error in button handler: {str(e)}")
        await handle_error(update, context, e)

async def cleanup_pending_payments():
    """Clean up old pending payments"""
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
                logger.info(f"Cleaned up pending payment {payment_id}")
                
        except Exception as e:
            logger.error(f"Error in payment cleanup: {str(e)}")
        
        await asyncio.sleep(3600)  # Run hourly

async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE, error: Exception):
    """Centralized error handling"""
    logger.error(f"Error occurred: {str(error)}", exc_info=error)
    
    error_message = f"""
{THEME['error']} *An Error Occurred*

We've encountered an unexpected error. Our technical team has been notified.

Please try your action again. If the problem persists, contact our support team.

{THEME['back']} You can return to the main menu below.
    """
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            error_message,
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    elif update.message:
        await update.message.reply_text(
            error_message,
            parse_mode='Markdown',
            reply_markup=back_button()
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler"""
    logger.error("Exception while handling update:", exc_info=context.error)
    
    error_details = f"""
{THEME['error']} *System Error Details*

• Error: `{context.error.__class__.__name__}`
• Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Update: {update.to_dict() if update else 'None'}
"""
    logger.error(error_details)
    
    if update and update.effective_message:
        user_message = f"""
{THEME['error']} *System Error*

We've encountered an unexpected error. Our technical team has been notified.

Please try your action again. If the problem persists, contact our support team.

{THEME['back']} You can return to the main menu below.
        """
        await update.effective_message.reply_text(
            user_message,
            parse_mode='Markdown',
            reply_markup=back_button()
        )

# ===== MAIN APPLICATION =====
# ===== MAIN APPLICATION =====
def main() -> None:
    """Start the bot"""
    async def post_init(app):
        logger.info("Bot initialization complete")
    
    async def post_stop(app):
        logger.info("Bot shutdown complete")

    application = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .post_init(post_init) \
        .post_stop(post_stop) \
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
    
    logger.info("Starting bot...")
    application.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()
