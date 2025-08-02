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

# Theme emojis
THEME = {
    'shield': '🛡️',
    'money': '💰',
    'kyc': '📝',
    'success': '✅',
    'verified': '☑️',
    'support': '🛠️'
}

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

# Popular cryptocurrencies including SOL and TRX
POPULAR_CRYPTOS = ['btc', 'eth', 'usdc', 'xmr', 'ton', 'sol', 'trx']

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

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
                return None, "This cryptocurrency is not supported for payments"
            return None, "Payment creation failed. Please try another method."
            
        return data, None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Invoice creation request failed: {str(e)}")
        return None, "Payment service unavailable. Please try again later."
    except ValueError as e:
        logger.error(f"Invalid JSON response: {str(e)}")
        return None, "Payment processing error. Please contact support."
    except Exception as e:
        logger.error(f"Invoice creation exception: {str(e)}")
        return None, "An unexpected error occurred. Please try again."

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

async def cleanup_pending_payments(context: ContextTypes.DEFAULT_TYPE):
    """Remove payment records that are too old and still pending"""
    try:
        now = datetime.datetime.now()
        to_remove = []
        
        for payment_id, payment in payment_history.items():
            if payment.get('status') == 'pending':
                payment_time = datetime.datetime.fromisoformat(payment['timestamp'])
                if (now - payment_time).days > 1:  # 1 day old
                    to_remove.append(payment_id)
        
        for payment_id in to_remove:
            del payment_history[payment_id]
            logger.info(f"Cleaned up old pending payment {payment_id}")
            
    except Exception as e:
        logger.error(f"Error in payment cleanup: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                f"✅ Payment successful! ${KYC_PRICE} has been added to your balance.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Order KYC", callback_data='order')],
                    [InlineKeyboardButton("📜 History", callback_data='history')]
                ])
            )
            return
        
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data='balance'),
             InlineKeyboardButton("💵 Deposit", callback_data='deposit')],
            [InlineKeyboardButton("🛒 Order KYC ($20)", callback_data='order')],
            [InlineKeyboardButton("📜 History", callback_data='history')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = f"""
{THEME['shield']} *Welcome to Fragment KYC Verification Service* {THEME['shield']}

🔐 *Premium KYC Verification Services*
✅ Trusted by thousands of users worldwide
⚡ Fast processing within 24 hours

💼 *Our Services:*
• Fragment.com KYC Verification
• Personal & Corporate account verification
• 100% success guarantee with money-back policy

📌 *How It Works:*
1. Deposit funds (${KYC_PRICE} per verification)
2. Submit your details through our secure form
3. Get verified within 24 hours

💰 *Payment Methods:*
We accept all major cryptocurrencies including BTC, ETH, USDC, SOL, and TRX

🔒 *Security Guarantee:*
All data is encrypted and processed securely. We never store sensitive information.

📢 *Support & Community:*
For any questions, please contact our support team @FragmentKYC_Support

Ready to get started? Choose an option below:
"""
        
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in start handler: {str(e)}")
        await error_handler(update, context)

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.from_user.id != ADMIN_ID:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        args = context.args
        if len(args) != 2:
            await update.message.reply_text(
                "ℹ️ Usage: /addbalance <user_id> <amount>\n"
                "Example: /addbalance 123456789 50"
            )
            return
        
        try:
            target_user_id = int(args[0])
            amount = float(args[1])
            
            if amount <= 0:
                await update.message.reply_text("❌ Amount must be positive.")
                return
            
            current_balance = user_balances.get(target_user_id, 0)
            user_balances[target_user_id] = current_balance + amount
            
            # Record in payment history
            payment_id = f"admin_{datetime.datetime.now().timestamp()}"
            payment_history[payment_id] = {
                'user_id': target_user_id,
                'amount': amount,
                'currency': 'USD',
                'status': 'completed',
                'address': 'Admin Manual Add',
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            await update.message.reply_text(
                f"✅ Added ${amount:.2f} to user {target_user_id}\n"
                f"New balance: ${user_balances[target_user_id]:.2f}"
            )
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 Admin has added ${amount:.2f} to your balance!\n"
                         f"Your new balance: ${user_balances[target_user_id]:.2f}\n\n"
                         "Click /start to continue"
                )
            except Exception as e:
                logger.error(f"Could not notify user {target_user_id}: {e}")
                await update.message.reply_text(f"⚠️ Could not notify user {target_user_id}")
                
        except ValueError:
            await update.message.reply_text("❌ Invalid arguments. Please provide user ID and amount as numbers.")
    except Exception as e:
        logger.error(f"Error in add_balance handler: {str(e)}")
        await error_handler(update, context)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /broadcast command"""
    try:
        if update.message.from_user.id != ADMIN_ID:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "ℹ️ Usage: /broadcast <message>\n"
                "Example: /broadcast Important system update!"
            )
            return
        
        message = " ".join(args)
        broadcast_messages.append({
            'text': message,
            'timestamp': datetime.datetime.now().isoformat(),
            'admin_id': update.message.from_user.id
        })
        
        await update.message.reply_text(
            "⚠️ Are you sure you want to broadcast this message to all users?\n\n"
            f"Message: {message}\n\n"
            "Click the buttons below to confirm or cancel:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm_broadcast")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]
            ])
        )
    except Exception as e:
        logger.error(f"Error in broadcast handler: {str(e)}")
        await error_handler(update, context)

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast confirmation"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ You are not authorized!", show_alert=True)
            return
        
        if not broadcast_messages:
            await query.edit_message_text("❌ No broadcast message to send.")
            return
        
        last_message = broadcast_messages[-1]
        message_text = last_message['text']
        
        # Initialize counters
        success_count = 0
        fail_count = 0
        
        # Get all chat IDs from active users
        all_chat_ids = set()
        all_chat_ids.update(user_balances.keys())
        all_chat_ids.update(payment_history.keys())
        all_chat_ids.update(pending_orders.keys())
        all_chat_ids.update(active_chats.keys())
        
        # Edit the original message to show "Broadcasting in progress..."
        await query.edit_message_text(
            "📤 Broadcasting in progress...\n\n"
            f"Message: {message_text}\n\n"
            "Please wait..."
        )
        
        # Send to all users
        for chat_id in all_chat_ids:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message_text
                )
                success_count += 1
                await asyncio.sleep(0.1)  # Small delay to avoid rate limiting
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {str(e)}")
                fail_count += 1
        
        # Update with final results
        await query.edit_message_text(
            f"✅ Broadcast completed!\n\n"
            f"📩 Sent to: {success_count} users\n"
            f"❌ Failed: {fail_count} users\n\n"
            f"Message: {message_text}"
        )
    except Exception as e:
        logger.error(f"Error in confirm_broadcast handler: {str(e)}")
        await error_handler(update, context)

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast cancellation"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ You are not authorized!", show_alert=True)
            return
        
        if broadcast_messages:
            broadcast_messages.pop()
        
        await query.edit_message_text("❌ Broadcast canceled.")
    except Exception as e:
        logger.error(f"Error in cancel_broadcast handler: {str(e)}")
        await error_handler(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        username = query.from_user.username or str(user_id)
        
        if query.data == "balance":
            balance = user_balances.get(user_id, 0)
            await query.edit_message_text(
                f"💰 *Your Account Balance*\n\n"
                f"Current Balance: ${balance:.2f}\n"
                f"KYC Verification Price: ${KYC_PRICE}\n\n"
                "Please choose an option below:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💵 Deposit Funds", callback_data='deposit')],
                    [InlineKeyboardButton("🛒 Order KYC", callback_data='order')],
                    [InlineKeyboardButton("🔙 Main Menu", callback_data='back')]
                ])
            )

        elif query.data == "deposit":
            buttons = []
            row = []
            for i, crypto in enumerate(POPULAR_CRYPTOS):
                row.append(InlineKeyboardButton(crypto.upper(), callback_data=f'pay_{crypto}'))
                if (i + 1) % 3 == 0:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "💎 *Select Payment Method*\n\n"
                "Please choose your preferred cryptocurrency for payment:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif query.data.startswith("pay_"):
            coin = query.data.split("_")[1].lower()
            if coin not in POPULAR_CRYPTOS:
                await query.edit_message_text(
                    "❌ Unsupported cryptocurrency selected",
                    reply_markup=back_button()
                )
                return
                
            invoice_data, error_msg = await create_invoice(user_id, coin)
            
            if error_msg:
                await query.edit_message_text(
                    f"❌ {error_msg}",
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
            
            # Reset payment check attempts
            payment_check_attempts[user_id] = 0
            
            await query.edit_message_text(
                f"💳 *{coin.upper()} Payment Invoice*\n\n"
                f"🔹 Amount Due: ${KYC_PRICE} USD\n"
                f"🔹 Payment ID: `{payment_id}`\n"
                f"🔹 Status: Pending\n\n"
                "Please complete your payment using the button below. "
                "After payment, you can check the status.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Pay Now", url=invoice_data['invoice_url'])],
                    [InlineKeyboardButton("🔄 Check Payment Status", callback_data=f'check_{payment_id}')],
                    [InlineKeyboardButton("🔙 Back to Deposit", callback_data='deposit')]
                ])
            )

        elif query.data.startswith("check_"):
            payment_id = query.data.split("_")[1]
            
            # First check if we have this payment in our history
            if payment_id not in payment_history:
                await query.answer("❌ Payment record not found", show_alert=True)
                return
            
            # Check if user has exceeded check attempts
            user_id = query.from_user.id
            payment_check_attempts[user_id] = payment_check_attempts.get(user_id, 0) + 1
            
            if payment_check_attempts[user_id] > MAX_PAYMENT_CHECKS:
                await query.answer(
                    f"❌ You've exceeded the maximum verification attempts. Please wait {CHECK_COOLDOWN//60} minutes or contact support.",
                    show_alert=True
                )
                return
            
            is_paid, payment_data = await check_payment_status(payment_id)
            
            if is_paid:
                user_id = payment_history[payment_id]['user_id']
                user_balances[user_id] = user_balances.get(user_id, 0) + KYC_PRICE
                payment_history[payment_id]['status'] = 'completed'
                payment_history[payment_id]['tx_hash'] = payment_data.get('payin_hash', 'N/A')
                
                # Reset check attempts
                payment_check_attempts[user_id] = 0
                
                await query.edit_message_text(
                    f"✅ *Payment Confirmed!*\n\n"
                    f"🔹 Amount: ${KYC_PRICE}\n"
                    f"🔹 Transaction Hash: {payment_data.get('payin_hash', 'N/A')}\n"
                    f"🔹 New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                    "What would you like to do next?",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Order KYC Verification", callback_data='order')],
                        [InlineKeyboardButton("📜 View Transaction History", callback_data='history')],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data='back')]
                    ])
                )
                
                # Send receipt to user
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📄 *Payment Receipt*\n\n"
                         f"🔹 Payment ID: {payment_id}\n"
                         f"🔹 Amount: ${KYC_PRICE}\n"
                         f"🔹 Currency: {payment_history[payment_id]['currency'].upper()}\n"
                         f"🔹 Status: Completed\n"
                         f"🔹 Transaction Hash: {payment_data.get('payin_hash', 'N/A')}\n"
                         f"🔹 Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode='Markdown'
                )
            else:
                # Check if the payment exists in our system but not in NowPayments
                if payment_history[payment_id]['status'] == 'pending':
                    remaining_attempts = MAX_PAYMENT_CHECKS - payment_check_attempts[user_id]
                    
                    # Show more detailed status
                    status_message = "⌛ Payment still processing"
                    if payment_data:
                        status_message = f"⌛ Current status: {payment_data.get('payment_status', 'pending').upper()}"
                    
                    await query.edit_message_text(
                        f"💳 *Payment Status Update*\n\n"
                        f"🔹 Payment ID: `{payment_id}`\n"
                        f"🔹 Amount: ${KYC_PRICE}\n"
                        f"🔹 Currency: {payment_history[payment_id]['currency'].upper()}\n"
                        f"🔹 Status: {payment_data.get('payment_status', 'PENDING').upper() if payment_data else 'PENDING'}\n"
                        f"🔹 Verification attempts remaining: {remaining_attempts}\n\n"
                        f"ℹ️ Cryptocurrency payments may take several minutes to process. "
                        f"You can check again shortly.",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Check Again", callback_data=f'check_{payment_id}')],
                            [InlineKeyboardButton("🔙 Back to Payments", callback_data='deposit')]
                        ])
                    )
                    
                    await query.answer(
                        f"{status_message}\nYou have {remaining_attempts} verification attempts remaining.",
                        show_alert=True
                    )
                else:
                    await query.answer(
                        "❌ Payment verification failed. Please contact support.",
                        show_alert=True
                    )

        elif query.data == "history":
            user_history = [
                payment for payment in payment_history.values() 
                if payment.get('user_id') == user_id
            ]
            
            if not user_history:
                await query.edit_message_text(
                    "📜 *Your Transaction History*\n\n"
                    "No transactions found in your history.",
                    parse_mode='Markdown',
                    reply_markup=back_button()
                )
                return
            
            history_text = "📜 *Your Transaction History*\n\n"
            for i, payment in enumerate(user_history[-10:], 1):  # Show last 10 payments
                history_text += (
                    f"{i}. {payment['timestamp'].split('T')[0]} - "
                    f"${payment['amount']} {payment.get('currency', 'USD').upper()} - "
                    f"{payment['status'].capitalize()}\n"
                )
            
            await query.edit_message_text(
                history_text,
                parse_mode='Markdown',
                reply_markup=back_button()
            )

        elif query.data == "order":
            balance = user_balances.get(user_id, 0)
            if balance >= KYC_PRICE:
                user_balances[user_id] = balance - KYC_PRICE
                pending_orders[user_id] = {
                    'username': username,
                    'timestamp': datetime.datetime.now().isoformat(),
                    'status': 'pending'
                }
                
                await query.edit_message_text(
                    f"✅ *KYC Order Placed!*\n\n"
                    f"🔹 Service: Fragment KYC Verification\n"
                    f"🔹 Price: ${KYC_PRICE}\n"
                    f"🔹 New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                    "Please click the button below to provide your details and complete the verification process.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Provide KYC Details", callback_data='chat_admin')],
                        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data='back')]
                    ])
                )
                
                # Notify admin
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ *New KYC Order*\n👤 User: @{username}\n🆔 ID: {user_id}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Start Verification Chat", callback_data=f"chat_{user_id}")],
                        [InlineKeyboardButton("✅ Mark as Complete", callback_data=f"done_{user_id}")]
                    ])
                )
            else:
                await query.edit_message_text(
                    f"❌ *Insufficient Balance*\n\n"
                    f"You need ${KYC_PRICE} to order KYC verification.\n"
                    f"Your current balance: ${balance:.2f}\n\n"
                    "Please deposit funds to continue.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💵 Deposit Funds", callback_data='deposit')],
                        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data='back')]
                    ])
                )

        elif query.data == "chat_admin":
            active_chats[user_id] = ADMIN_ID
            await query.edit_message_text(
                "💬 *KYC Verification Process*\n\n"
                "You are now connected to our verification specialist.\n\n"
                "To complete your Fragment KYC verification, please provide the following details:\n"
                "1. Your Telegram phone number (for login)\n"
                "2. Email address\n"
                "3. Preferred username for the form\n\n"
                "Our specialist will guide you through the rest of the process.\n\n"
                "🔒 *All information is kept confidential and encrypted*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data='back')]
                ])
            )
            
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💬 *New KYC Verification Request*\nUser: @{username}\nID: {user_id}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Start Verification", callback_data=f"chat_{user_id}")]
                ])
            )

        elif query.data.startswith("chat_"):
            if query.from_user.id != ADMIN_ID:
                return
                
            target_user_id = int(query.data.split("_")[1])
            active_chats[target_user_id] = ADMIN_ID
            
            await query.edit_message_text(
                f"💬 *KYC Verification Session*\n\n"
                f"You are now chatting with user ID: {target_user_id}\n\n"
                "Type /endchat to stop the session when complete.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Complete Verification", callback_data=f"done_{target_user_id}")]
                ])
            )
            
            await context.bot.send_message(
                chat_id=target_user_id,
                text="👋 *Verification Specialist Connected*\n\n"
                     "Please provide the requested details to complete your KYC verification:",
                parse_mode='Markdown'
            )

        elif query.data.startswith("done_"):
            if query.from_user.id != ADMIN_ID:
                return
                
            target_user_id = int(query.data.split("_")[1])
            if target_user_id in pending_orders:
                pending_orders[target_user_id]['status'] = 'completed'
            
            if target_user_id in active_chats:
                del active_chats[target_user_id]
            
            await query.edit_message_text(f"✅ Verification for user {target_user_id} completed")
            
            await context.bot.send_message(
                chat_id=target_user_id,
                text="🎉 *KYC Verification Complete!*\n\n"
                     "Your Fragment KYC verification has been successfully processed.\n\n"
                     "Thank you for using our service!",
                parse_mode='Markdown'
            )

        elif query.data == "back":
            await start(update, context)

        elif query.data == "confirm_broadcast":
            await confirm_broadcast(update, context)

        elif query.data == "cancel_broadcast":
            await cancel_broadcast(update, context)

    except Exception as e:
        logger.error(f"Error in button handler: {str(e)}")
        await error_handler(update, context)

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                                text=f"👨‍💼 *Admin*: {update.message.text}",
                                parse_mode='Markdown'
                            )
                        elif update.message.photo:
                            await context.bot.send_photo(
                                chat_id=target_id,
                                photo=update.message.photo[-1].file_id,
                                caption=f"👨‍💼 *Admin*: {update.message.caption or ''}",
                                parse_mode='Markdown'
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
                        text=f"👤 *User @{username}*: {update.message.text}",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💬 Reply", callback_data=f"chat_{user_id}")]
                        ])
                    )
                elif update.message.photo:
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=update.message.photo[-1].file_id,
                        caption=f"👤 *User @{username}*: {update.message.caption or ''}",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💬 Reply", callback_data=f"chat_{user_id}")]
                        ])
                    )
            except Exception as e:
                logger.error(f"Error forwarding user message: {e}")
    except Exception as e:
        logger.error(f"Error in handle_messages: {str(e)}")
        await error_handler(update, context)

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await update.message.reply_text(f"✅ Ended chat with {target_user_id}")
            await context.bot.send_message(
                chat_id=target_user_id,
                text="ℹ️ *Chat Session Ended*\n\n"
                     "The verification specialist has ended the chat session.\n\n"
                     "If you have any further questions, please contact support.",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error in end_chat handler: {str(e)}")
        await error_handler(update, context)

async def vouch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        args = context.args

        if not args:
            await update.message.reply_text(
                "❗ *Vouch Submission*\n\n"
                "Please include your testimonial about our service.\n\n"
                "Example:\n"
                "/vouch Excellent service! Fast and professional verification process.",
                parse_mode='Markdown'
            )
            return

        vouch_text = " ".join(args)

        # Store the vouch
        vouches[user.id] = {
            "text": vouch_text,
            "username": user.username or f"user_{user.id}",
            "timestamp": datetime.datetime.now().isoformat()
        }

        # Format the vouch message
        message = (
            "🌟 *New Customer Testimonial*\n\n"
            f"✉️ *Review*: {vouch_text}\n\n"
            f"*Fragment KYC Verification Service* - {vouch_text}"
        )

        # Create buttons
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=f"Submitted by: @{vouches[user.id]['username']}",
                url=f"tg://user?id={user.id}"
            )
        ]])

        # Send to the vouch channel
        sent = await context.bot.send_message(
            chat_id=VOUCH_CHANNEL_ID,
            text=message,
            parse_mode='Markdown',
            reply_markup=buttons
        )

        # Confirm to the user with link to their vouch
        await update.message.reply_text(
            "✅ *Thank You for Your Feedback!*\n\n"
            "Your testimonial has been published in our community channel.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "👀 View Your Testimonial", 
                    url=f"https://t.me/c/{str(VOUCH_CHANNEL_ID)[4:]}/{sent.message_id}"
                )
            ]])
        )
    except Exception as e:
        logger.error(f"Error in vouch handler: {str(e)}")
        await error_handler(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ *An Error Occurred*\n\n"
                "We encountered an unexpected error. Our team has been notified.\n\n"
                "Please try again later or contact support if the issue persists.",
                parse_mode='Markdown',
                reply_markup=back_button()
            )
    except Exception as e:
        logger.error(f"Error in error handler itself: {str(e)}")

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
    
    # Add cleanup job
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            cleanup_pending_payments,
            interval=3600,  # Run every hour
            first=10  # Start after 10 seconds
        )
    
    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
