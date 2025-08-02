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
    text = """ *Welcome to Fragment KYC Verification* 

🔐 *Secure & Affordable KYC Service*
✅ Trusted by 100+ users worldwide
⚡ Fast processing within minutes

📌 *How it works:*
1. Deposit funds (${KYC_PRICE} per verification)
2. Submit your details securely
3. Get verified within minutes

📢 *Community:*
Reviews: [View Testimonials](https://t.me/YourReviewsChannel)
Support: @YourSupportBot"""
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                text=f"🎉 Admin has added ${amount:.2f} to your balance! click /start \n"
                     f"Your new balance: ${user_balances[target_user_id]:.2f}"
            )
        except Exception as e:
            logger.error(f"Could not notify user {target_user_id}: {e}")
            await update.message.reply_text(f"⚠️ Could not notify user {target_user_id}")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid arguments. Please provide user ID and amount as numbers.")
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /broadcast command"""
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

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast confirmation"""
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
    
    # Get all chat IDs from your database
    # This is a placeholder - implement your actual user retrieval
    all_chat_ids = get_all_chat_ids()  # You need to implement this
    
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
        except Exception as e:
            print(f"Failed to send to {chat_id}: {str(e)}")
            fail_count += 1
    
    # Update with final results
    await query.edit_message_text(
        f"✅ Broadcast completed!\n\n"
        f"📩 Sent to: {success_count} users\n"
        f"❌ Failed: {fail_count} users\n\n"
        f"Message: {message_text}"
    )

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast cancellation"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ You are not authorized!", show_alert=True)
        return
    
    await query.edit_message_text("❌ Broadcast cancelled.")

# Add these to your main application
def setup_broadcast_handlers(application):
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
    application.add_handler(CallbackQueryHandler(cancel_broadcast, pattern="^cancel_broadcast$"))

# Example user database function - IMPLEMENT THIS PROPERLY
def get_all_chat_ids():
    """Retrieve all chat IDs that should receive broadcasts"""
    # This should return a list of chat IDs from your database
    # Example: return [12345, 67890] 
    return []  # Replace with actual implementation
async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ You are not authorized!", show_alert=True)
        return
    
    if broadcast_messages:
        broadcast_messages.pop()
    
    await query.edit_message_text("❌ Broadcast canceled.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    try:
        if query.data == "balance":
            balance = user_balances.get(user_id, 0)
            await query.edit_message_text(
                f"💳 Balance: ${balance:.2f}\nKYC Price: ${KYC_PRICE}",
                reply_markup=back_button()
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
                "💎 Choose payment method:",
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
                f"💳 *{coin.upper()} Payment*\n\n"
                f"🔹 Amount: ${KYC_PRICE} USD\n"
                f"🔹 Payment ID: `{payment_id}`\n"
                f"🔹 Status: Waiting for payment\n\n"
                "Click the button below to pay:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Pay Now", url=invoice_data['invoice_url'])],
                    [InlineKeyboardButton("🔄 Check Payment", callback_data=f'check_{payment_id}')],
                    [InlineKeyboardButton("🔙 Back", callback_data='deposit')]
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
                    f"✅ Payment confirmed!\n\n"
                    f"🔹 Amount: ${KYC_PRICE}\n"
                    f"🔹 Transaction: {payment_data.get('payin_hash', 'N/A')}\n"
                    f"🔹 New Balance: ${user_balances.get(user_id, 0):.2f}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Order KYC", callback_data='order')],
                        [InlineKeyboardButton("📜 History", callback_data='history')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back')]
                    ])
                )
                
                # Send receipt to user
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"💰 Payment Receipt\n\n"
                         f"🔹 ID: {payment_id}\n"
                         f"🔹 Amount: ${KYC_PRICE}\n"
                         f"🔹 Currency: {payment_history[payment_id]['currency'].upper()}\n"
                         f"🔹 Status: Completed\n"
                         f"🔹 Hash: {payment_data.get('payin_hash', 'N/A')}\n"
                         f"🔹 Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
                        f"💳 Payment Status\n\n"
                        f"🔹 ID: `{payment_id}`\n"
                        f"🔹 Amount: ${KYC_PRICE}\n"
                        f"🔹 Currency: {payment_history[payment_id]['currency'].upper()}\n"
                        f"🔹 Status: {payment_data.get('payment_status', 'PENDING').upper() if payment_data else 'PENDING'}\n"
                        f"🔹 Attempts left: {remaining_attempts}\n\n"
                        f"ℹ️ You can check again in a few minutes",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Check Again", callback_data=f'check_{payment_id}')],
                            [InlineKeyboardButton("🔙 Back", callback_data='deposit')]
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
                if payment['user_id'] == user_id
            ]
            
            if not user_history:
                await query.edit_message_text(
                    "📜 No payment history found",
                    reply_markup=back_button()
                )
                return
            
            history_text = "📜 Your Payment History:\n\n"
            for i, payment in enumerate(user_history[-10:], 1):  # Show last 10 payments
                history_text += (
                    f"{i}. {payment['timestamp'].split('T')[0]} - "
                    f"${payment['amount']} {payment['currency'].upper()} - "
                    f"{payment['status'].capitalize()}\n"
                )
            
            await query.edit_message_text(
                history_text,
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
                    f"✅ KYC Order Placed!\n\n"
                    f"🔹 Price: ${KYC_PRICE}\n"
                    f"🔹 New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                    "Click Kyc and provide details",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 click kyc", callback_data='chat_admin')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back')]
                    ])
                )
                
                # Notify admin
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ New KYC Order\n👤 User: @{username}\n🆔 ID: {user_id}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Chat", callback_data=f"chat_{user_id}")],
                        [InlineKeyboardButton("✅ Complete", callback_data=f"done_{user_id}")]
                    ])
                )
            else:
                await query.edit_message_text(
                    f"❌ Insufficient balance. You need ${KYC_PRICE}",
                    reply_markup=back_button()
                )

        elif query.data == "chat_admin":
            active_chats[user_id] = ADMIN_ID
            await query.edit_message_text(
                "💬 You are now chatting with admin\n\n"
                "Welcome!\n"
                "Thank you for choosing my Fragment KYC service.\n\n"
                "To get started, I'll need your Telegram phone number to log in.\n"
                "Once I send the login request, please approve it on your end.\n\n"
                "After that, to complete the verification, I'll need the following details:\n"
                "• Phone Number\n"
                "• Email Address\n"
                "• Preferred Username (for the form)\n\n"
                "Let me know when you're ready — and thanks again for trusting my service.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data='back')]
                ])
            )
            
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💬 User @{username} ({user_id}) wants to chat",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Reply", callback_data=f"chat_{user_id}")]
                ])
            )

        elif query.data.startswith("chat_"):
            if query.from_user.id != ADMIN_ID:
                return
                
            target_user_id = int(query.data.split("_")[1])
            active_chats[target_user_id] = ADMIN_ID
            
            await query.edit_message_text(
                f"💬 Chatting with user {target_user_id}\n"
                "Type /endchat to stop",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Complete Order", callback_data=f"done_{target_user_id}")]
                ])
            )
            
            await context.bot.send_message(
                chat_id=target_user_id,
                text="👋 Admin is now chatting with you. Please send your details:"
            )

        elif query.data.startswith("done_"):
            if query.from_user.id != ADMIN_ID:
                return
                
            target_user_id = int(query.data.split("_")[1])
            if target_user_id in pending_orders:
                pending_orders[target_user_id]['status'] = 'completed'
            
            if target_user_id in active_chats:
                del active_chats[target_user_id]
            
            await query.edit_message_text(f"✅ Order for {target_user_id} completed")
            
            await context.bot.send_message(
                chat_id=target_user_id,
                text="🎉 Your KYC is complete! Thank you."
            )

        elif query.data == "back":
            await start(update, context)

        elif query.data == "confirm_broadcast":
            await confirm_broadcast(update, context)

        elif query.data == "cancel_broadcast":
            await cancel_broadcast(update, context)

    except Exception as e:
        logger.error(f"Error in button handler: {str(e)}")
        await query.edit_message_text(
            "❌ An error occurred",
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
        await update.message.reply_text(f"✅ Ended chat with {target_user_id}")
        await context.bot.send_message(
            chat_id=target_user_id,
            text="ℹ️ Admin has ended the chat"
        )

async def vouch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            "❗ Please include your vouch text.\nExample:\n/vouch great service!"
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
        "🌟 New Vouch for Fkyc $20\n\n"
        f"✉️ {vouch_text}\n\n"
        f"Vouch Fkyc $20 - {vouch_text}"
    )

    # Create buttons
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text=f"sent by: @{vouches[user.id]['username']}",
            url=f"tg://user?id={user.id}"
        )
    ]])

    # Send to the vouch channel
    sent = await context.bot.send_message(
        chat_id=VOUCH_CHANNEL_ID,
        text=message,
        reply_markup=buttons
    )

    # Confirm to the user with link to their vouch
    await update.message.reply_text(
        "✅ Your vouch has been submitted!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("👀 View it", url=f"https://t.me/c/{str(VOUCH_CHANNEL_ID)[4:]}/{sent.message_id}")
        ]])
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An unexpected error occurred. Please try again later.",
            reply_markup=back_button()
        )

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
    application.add_handler(CommandHandler("confirmbroadcast", confirm_broadcast))
    application.add_handler(CommandHandler("cancelbroadcast", cancel_broadcast))
    
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
