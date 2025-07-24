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
VOUCH_CHANNEL_ID = -1002873539878
MAX_PAYMENT_CHECKS = 3
CHECK_COOLDOWN = 600
SUPPORT_CHAT_ID = "@Fragkycsupportbot"

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
payment_check_attempts = {}
vouches = {}

# Popular cryptocurrencies
POPULAR_CRYPTOS = ['btc', 'eth', 'usdc', 'xmr', 'ton', 'sol', 'trx']

# Theme colors and emojis
THEME = {
    "primary": "🔵",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "info": "ℹ️",
    "money": "💵",
    "kyc": "🆔",
    "support": "🆘"
}

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{THEME['warning']} Back", callback_data="back")]])

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
            "success_url": f"https://t.me/Fragmentkyc_bot?start=success_{user_id}",
            "cancel_url": f"https://t.me/Fragmentkyc_bot?start=cancel_{user_id}"
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'invoice_url' not in data:
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Invoice creation error: {error_msg}")
            if "Currency" in error_msg and "not supported" in error_msg:
                return None, "This cryptocurrency is not supported for payments"
            return None, "Payment creation failed. Please try another method."
            
        return data, None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Invoice creation request failed: {str(e)}")
        return None, "Payment service unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, "An unexpected error occurred. Please try again."

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
            f"{THEME['success']} *Payment Successful!*\n\n"
            f"• Amount: *${KYC_PRICE}* has been added to your balance\n"
            f"• New Balance: *${user_balances[user_id]:.2f}*\n\n"
            "What would you like to do next?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['kyc']} Order KYC", callback_data='order')],
                [InlineKeyboardButton(f"{THEME['money']} View Balance", callback_data='balance')],
                [InlineKeyboardButton(f"{THEME['info']} History", callback_data='history')]
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
Reviews: @knowurcustomer
Support: @Fragkycsupportbot
    """
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')]
        ])
    )

async def vouch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    vouch_message = f"""
⭐ *Share Your Experience* ⭐

We value your feedback! Please share your experience with our KYC service.

Your vouch will be posted in our community channel @knowurcustomer and helps others trust our service.

To leave feedback, use the /vouch command followed by your message:

Example:
`/vouch Excellent service! Got verified in 10 minutes.`
    """
    
    await query.edit_message_text(
        vouch_message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 View Testimonials", url=f"https://t.me/knowurcustomer")],
            [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')]
        ])
    )

async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')]
        ])
    )

async def deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    deposit_message = f"""
{THEME['money']} *Deposit Funds* {THEME['money']}

Choose your preferred payment method to add funds to your account balance.

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
    buttons.append([InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')])
    
    await query.edit_message_text(
        deposit_message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def payment_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    coin = query.data.split("_")[1].lower()
    
    invoice_data, error_msg = await create_invoice(user_id, coin)
    
    if error_msg:
        await query.edit_message_text(
            f"{THEME['error']} *Payment Error*\n\n{error_msg}",
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
            [InlineKeyboardButton("🔄 Check Payment", callback_data=f'check_{payment_id}')],
            [InlineKeyboardButton(f"{THEME['warning']} Cancel", callback_data='deposit')]
        ])
    )

async def check_payment_status(payment_id):
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

async def payment_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')]
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
                [InlineKeyboardButton("🔄 Check Again", callback_data=f'check_{payment_id}')],
                [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='deposit')]
            )
        )
        
        await query.answer(
            f"{status_message}\nAttempts remaining: {remaining_attempts}",
            show_alert=True
        )

async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

Please provide your details to complete the verification process.
        """
        
        await query.edit_message_text(
            order_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['support']} Provide Details", callback_data='chat_admin')],
                [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')]
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

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    if query.data == "chat_admin":
        active_chats[user_id] = ADMIN_ID
        welcome_message = f"""
{THEME['support']} *Support Chat* {THEME['support']}

Thank you for choosing Fragment KYC service!

To complete your verification, please provide:
1. Telegram phone number (for login)
2. Email address
3. Preferred username

We'll guide you through the entire process.
        """
        
        await query.edit_message_text(
            welcome_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['warning']} Back", callback_data='back')]
            ])
        )
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💬 User @{username} ({user_id}) started a chat",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{THEME['support']} Reply", callback_data=f"chat_{user_id}")]
            )
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
                [InlineKeyboardButton(f"{THEME['warning']} End Chat", callback_data=f"endchat_{target_user_id}")]
            )
        )
        
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"{THEME['support']} Admin is now chatting with you. Please send your details:"
        )

async def complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

Thank you for using our service! Your Fragment.com account has been successfully verified.

⭐ Please consider leaving feedback with /vouch command to help others trust our service.
    """
    
    await context.bot.send_message(
        chat_id=target_user_id,
        text=completion_message,
        parse_mode='Markdown'
    )

async def vouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            f"{THEME['info']} Please include your feedback text.\nExample:\n`/vouch Great service! Verified in 10 minutes.`",
            parse_mode='Markdown'
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
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
            
    except Exception as e:
        logger.error(f"Error in button handler: {str(e)}")
        await query.edit_message_text(
            f"{THEME['error']} An error occurred",
            reply_markup=back_button()
        )

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    )
                )
            elif update.message.photo:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=update.message.photo[-1].file_id,
                    caption=f"👤 User @{username}: {update.message.caption or ''}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Reply", callback_data=f"chat_{user_id}")]
                    )
                )
        except Exception as e:
            logger.error(f"Error forwarding user message: {e}")

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    
    target_user_id = None
    for user_id, admin_id in active_chats.items():
        if admin_id == update.message.from_user.id:
            target_user_id = user_id
            break
    
    if target_user_id:
        del active_chats[target_user_id]
        await update.message.reply_text(f"{THEME['success']} Ended chat with {target_user_id}")
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"{THEME['info']} Admin has ended the chat"
        )

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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            f"{THEME['error']} An unexpected error occurred. Please try again later.",
            reply_markup=back_button()
        )

def main() -> None:
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("endchat", end_chat))
    application.add_handler(CommandHandler("vouch", vouch_command))
    application.add_handler(CommandHandler("addbalance", add_balance))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("confirmbroadcast", confirm_broadcast))
    application.add_handler(CommandHandler("cancelbroadcast", cancel_broadcast))
    
    # Callback and message handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    application.add_handler(MessageHandler(filters.PHOTO, handle_messages))
    
    # Start cleanup task
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(cleanup_pending_payments()),
        when=5
    )
    
    application.run_polling()

if __name__ == '__main__':
    main()
