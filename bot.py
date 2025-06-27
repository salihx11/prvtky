import logging
import requests
import telegram
import datetime
import qrcode
import asyncio
from io import BytesIO
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    Application,
)

# Constants
BOT_TOKEN = '7937591717:AAENsuVdvNbmnjnewIhhCk0Rtgv79dz3Mg8'
ADMIN_ID = 7017391282
NOWPAYMENTS_API_KEY = 'BJMQ1ZZ-K8JMX4G-GY0EP0N-V210854'
KYC_PRICE = 20  # Fixed price for KYC verification
WEBAPP_URL = "https://coinspark.pro/kyc/index.php"

# Payment addresses
PAYMENT_ADDRESSES = {
    'usdt': 'TM252nTSTo62q3JwTbeH9qPwSbbrXUrnF8',
    'btc': 'bc1qlmt2hlyxvqk9dwmlywvpj6emu6rpdp57gpn5vn',
    'trx': 'TM252nTSTo62q3JwTbeH9qPwSbbrXUrnF8',
    'ltc': 'ltc1qlmt2hlyxvqk9dwmlywvpj6emu6rpdp57vafs5r',
    'usdc': '0x7933Fa706A842ca6e2E3DB300b1789e5BC8516d1',
    'sol': 'Bsam7cG6Y7Gwevdwjkp1kSccXZSExdswL7U93P1P5Zr9',
    'xmr': '41pb6PDhkACAJ1oS7N7RYdgoNFtGjwwDQRxME75786Jh9hAdu7TYvtK4xbUZWqL5wBNiEnVcbaaopB6AdZfQvMaKFr37WcT',
    'bnb': '0x7933Fa706A842ca6e2E3DB300b1789e5BC8516d1',
    'ton': 'EQAj7vKLbaWjaNbAuAKP1e1HwmdYZ2vJ2xtWU8qq3JafkfxF'
}

MIN_AMOUNTS = {
    'usdt': 5, 'btc': 5, 'trx': 5, 'ltc': 5, 
    'usdc': 5, 'sol': 5, 'xmr': 5, 'bnb': 5, 'ton': 5
}

# Global variables
user_balances = {}
user_invoices = {}
payment_history = {}
pending_orders = {}

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

def convert_coin_name(coin):
    mapping = {
        "usdt": "usdttrc20",
        "usdc": "usdc",
        "bnb": "bnb",
        "ltc": "ltc",
        "trx": "trx",
        "sol": "sol",
        "xmr": "xmr",
        "ton": "ton"
    }
    return mapping.get(coin.lower(), coin.lower())

async def get_min_amount(coin_code):
    try:
        url = f"https://api.nowpayments.io/v1/min-amount?currency_from=usd&currency_to={coin_code}"
        headers = {"x-api-key": NOWPAYMENTS_API_KEY}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return float(data.get("min_amount", MIN_AMOUNTS.get(coin_code, 5)))
        logger.error(f"Min amount API error: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Min amount fetch error: {str(e)}")
    return MIN_AMOUNTS.get(coin_code, 5)

async def check_payment_status(invoice_id):
    try:
        headers = {"x-api-key": NOWPAYMENTS_API_KEY}
        response = requests.get(
            f"https://api.nowpayments.io/v1/payment/{invoice_id}",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("payment_status"), float(data.get("actually_paid", 0))
        return "error", 0
    except Exception as e:
        logger.error(f"Check payment error: {str(e)}")
        return "error", 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data='balance'),
         InlineKeyboardButton("💵 Deposit", callback_data='deposit')],
        [InlineKeyboardButton("🛒 Order KYC ($20)", callback_data='order')],
        [InlineKeyboardButton("📜 History", callback_data='history')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🥳 Welcome to the @Fragmentkyc_bot - We provide fragment KYC verification services with fast, secure, and professional handling. Get your KYC done perfectly for just $20. Stay updated at @Fkyc_chanel."
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except telegram.error.BadRequest:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    try:
        if query.data == "balance":
            balance = user_balances.get(user_id, 0)
            new_text = f"💳 Your current balance: ${balance:.2f}\n\nKYC Verification Price: ${KYC_PRICE}"
            try:
                await query.edit_message_text(
                    new_text,
                    reply_markup=back_button()
                )
            except telegram.error.BadRequest:
                await query.message.reply_text(
                    new_text,
                    reply_markup=back_button()
                )

        elif query.data == "deposit":
            deposit_menu = {
                'text': "💎 Choose your payment method (Minimum $5 USD equivalent):",
                'reply_markup': [
                    [InlineKeyboardButton("USDT (TRC20)", callback_data='pay_usdt'), 
                     InlineKeyboardButton("BTC (Bitcoin)", callback_data='pay_btc')],
                    [InlineKeyboardButton("TRX (Tron)", callback_data='pay_trx'), 
                     InlineKeyboardButton("LTC (Litecoin)", callback_data='pay_ltc')],
                    [InlineKeyboardButton("USDC (ERC20)", callback_data='pay_usdc'), 
                     InlineKeyboardButton("SOL (Solana)", callback_data='pay_sol')],
                    [InlineKeyboardButton("XMR (Monero)", callback_data='pay_xmr'), 
                     InlineKeyboardButton("BNB (BSC)", callback_data='pay_bnb')],
                    [InlineKeyboardButton("TON (Toncoin)", callback_data='pay_ton')],
                    [InlineKeyboardButton("🔙 Back", callback_data='back')]
                ]
            }
            context.user_data['deposit_menu'] = deposit_menu
            try:
                await query.edit_message_text(
                    deposit_menu['text'],
                    reply_markup=InlineKeyboardMarkup(deposit_menu['reply_markup'])
                )
            except telegram.error.BadRequest:
                await query.message.reply_text(
                    deposit_menu['text'],
                    reply_markup=InlineKeyboardMarkup(deposit_menu['reply_markup'])
                )

        elif query.data.startswith("pay_"):
            coin = query.data.split("_")[1]
            coin_code = convert_coin_name(coin)
            min_amount = await get_min_amount(coin_code)
            address = PAYMENT_ADDRESSES.get(coin, "Address not available")
            
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(address)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            bio = BytesIO()
            bio.name = 'qr.png'
            img.save(bio, 'PNG')
            bio.seek(0)
            
            message = (
                f"💳 *{coin.upper()} Deposit*\n\n"
                f"🔹 *Minimum Amount:* ${min_amount:.2f} USD equivalent\n"
                f"🔹 *Wallet Address:*\n`{address}`\n\n"
                "Scan the QR code below to send payment.\n"
                "Your balance will be updated after confirmation."
            )
            
            user_invoices[user_id] = {
                'invoice_id': f"manual_{datetime.datetime.now().timestamp()}",
                'coin': coin,
                'address': address,
                'min_amount': min_amount,
                'status': 'pending',
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            try:
                await query.edit_message_media(
                    media=InputMediaPhoto(
                        media=bio,
                        caption=message,
                        parse_mode='Markdown'
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Check Payment", callback_data='check_payment')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back_to_deposit')]
                    ])
                )
            except telegram.error.BadRequest:
                await query.message.reply_photo(
                    photo=bio,
                    caption=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Check Payment", callback_data='check_payment')],
                        [InlineKeyboardButton("🔙 Back", callback_data='back_to_deposit')]
                    ])
                )

        elif query.data == "back_to_deposit":
            if 'deposit_menu' in context.user_data:
                try:
                    await query.edit_message_text(
                        text=context.user_data['deposit_menu']['text'],
                        reply_markup=InlineKeyboardMarkup(context.user_data['deposit_menu']['reply_markup'])
                    )
                except telegram.error.BadRequest:
                    await query.message.reply_text(
                        text=context.user_data['deposit_menu']['text'],
                        reply_markup=InlineKeyboardMarkup(context.user_data['deposit_menu']['reply_markup'])
                    )
                    await asyncio.sleep(6)
                    try:
                        await sent.delete()
                    except:
                        pass
            else:
                await start(update, context)

        elif query.data == "check_payment":
            payment_info = user_invoices.get(user_id)
            if not payment_info:
                try:
                    await query.edit_message_text(
                        "❌ No active payment found. Please create a new deposit.",
                        reply_markup=back_button()
                    )
                except telegram.error.BadRequest:
                    await query.message.reply_text(
                        "❌ No active payment found. Please create a new deposit.",
                        reply_markup=back_button()
                    )
                return
                
            try:
                await query.edit_message_text(
                    "⚡ Checking payment status...",
                    reply_markup=None
                )
            except telegram.error.BadRequest:
                await query.message.reply_text(
                    "⚡ Checking payment status...",
                    reply_markup=None
                )
            
            status, paid_amount = await check_payment_status(payment_info.get('invoice_id', ''))
            
            if status == "finished":
                usd_amount = float(paid_amount)
                user_balances[user_id] = user_balances.get(user_id, 0) + usd_amount
                payment_info['status'] = 'completed'
                
                payment_history[payment_info['invoice_id']] = {
                    'user_id': user_id,
                    'amount': paid_amount,
                    'currency': payment_info['coin'],
                    'status': 'completed',
                    'usd_value': usd_amount,
                    'timestamp': payment_info['timestamp']
                }
                
                try:
                    sent = await query.edit_message_text(
                        f"✅ Payment confirmed! ${usd_amount:.2f} added to your balance.\n\n"
                        f"New balance: ${user_balances.get(user_id, 0):.2f}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Refresh", callback_data='check_payment')]
                        ])
                    )
                except telegram.error.BadRequest:
                    sent = await query.message.reply_text(
                        f"✅ Payment confirmed! ${usd_amount:.2f} added to your balance.\n\n"
                        f"New balance: ${user_balances.get(user_id, 0):.2f}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Refresh", callback_data='check_payment')]
                        ])
                    )

                await asyncio.sleep(6)
                try:
                    await sent.delete()
                except:
                    pass

            elif status in ["waiting", "confirming"]:
                try:
                    sent = await query.edit_message_text(
                        "⌛ Payment detected but waiting for confirmations.\n\n"
                        "This usually takes 2-3 minutes. Please check again shortly.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Refresh", callback_data='check_payment')]
                        ])
                    )
                except telegram.error.BadRequest:
                    sent = await query.message.reply_text(
                        "⌛ Payment detected but waiting for confirmations.\n\n"
                        "This usually takes 2-3 minutes. Please check again shortly.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Refresh", callback_data='check_payment')]
                        ])
                    )

                await asyncio.sleep(6)
                try:
                    await sent.delete()
                except:
                    pass

            else:
                try:
                    sent = await query.edit_message_text(
                        "❌ Payment not confirmed yet. Please complete the payment first.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data='check_payment')]
                        ])
                    )
                except telegram.error.BadRequest:
                    sent = await query.message.reply_text(
                        "❌ Payment not confirmed yet. Please complete the payment first.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data='check_payment')]
                        ])
                    )

                await asyncio.sleep(6)
                try:
                    await sent.delete()
                except:
                    pass

        elif query.data == "order":
            try:
                balance = user_balances.get(user_id, 0)
                if balance >= KYC_PRICE:
                    user_balances[user_id] = balance - KYC_PRICE
                    
                    pending_orders[user_id] = {
                        'username': username,
                        'timestamp': datetime.datetime.now().isoformat(),
                        'status': 'pending'
                    }
                    
                    webapp_url = f"{WEBAPP_URL}?id={user_id}"
                    
                    try:
                        await query.edit_message_text(
                            f"✅ KYC Order Placed Successfully!\n\n"
                            f"🔹 Price: ${KYC_PRICE}\n"
                            f"🔹 New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                            "Click below to complete your verification:",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton(
                                    text="🔐 Complete KYC Verification", 
                                    web_app=WebAppInfo(url=webapp_url)
                                )],
                                [InlineKeyboardButton("🔙 Back", callback_data='back')]
                            ])
                        )
                    except telegram.error.BadRequest:
                        await query.message.reply_text(
                            f"✅ KYC Order Placed Successfully!\n\n"
                            f"🔹 Price: ${KYC_PRICE}\n"
                            f"🔹 New Balance: ${user_balances.get(user_id, 0):.2f}\n\n"
                            "Click below to complete your verification:",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton(
                                    text="🔐 Complete KYC Verification", 
                                    web_app=WebAppInfo(url=webapp_url)
                                )],
                                [InlineKeyboardButton("🔙 Back", callback_data='back')]
                            ])
                        )
                    
                    admin_message = (
                        f"⚠️ *New KYC Order*\n"
                        f"👤 User: @{username}\n"
                        f"🆔 ID: `{user_id}`\n"
                        f"💰 Paid: ${KYC_PRICE}\n"
                        f"⏰ Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"🥶 See order: /vieworders"
                    )
                    
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=admin_message,
                        parse_mode='Markdown'
                    )

                else:
                    try:
                        await query.edit_message_text(
                            f"❌ Insufficient balance. You need ${KYC_PRICE} (Current: ${balance:.2f})\n\n"
                            "Please deposit more funds and try again.",
                            reply_markup=back_button()
                        )
                    except telegram.error.BadRequest:
                        await query.message.reply_text(
                            f"❌ Insufficient balance. You need ${KYC_PRICE} (Current: ${balance:.2f})\n\n"
                            "Please deposit more funds and try again.",
                            reply_markup=back_button()
                        )
            except Exception as e:
                logger.error(f"Order processing error: {str(e)}")
                try:
                    await query.edit_message_text(
                        "❌ An error occurred while processing your order. Please try again.",
                        reply_markup=back_button()
                    )
                except telegram.error.BadRequest:
                    await query.message.reply_text(
                        "❌ An error occurred while processing your order. Please try again.",
                        reply_markup=back_button()
                    )
                if user_id in pending_orders:
                    user_balances[user_id] += KYC_PRICE
                    del pending_orders[user_id]

        elif query.data == "history":
            user_payments = [p for p in payment_history.values() if p['user_id'] == user_id]
            if not user_payments:
                try:
                    await query.edit_message_text(
                        "📜 You don't have any payment history yet.",
                        reply_markup=back_button()
                    )
                except telegram.error.BadRequest:
                    await query.message.reply_text(
                        "📜 You don't have any payment history yet.",
                        reply_markup=back_button()
                    )
                return
                
            history_text = "📜 Your Payment History:\n\n"
            for payment in user_payments[-5:]:
                history_text += (
                    f"🔹 {payment.get('timestamp', 'N/A')}\n"
                    f"Amount: {payment.get('amount', 'N/A')} {payment.get('currency', 'N/A')}\n"
                    f"Status: {payment.get('status', 'N/A').capitalize()}\n"
                    f"USD Value: ${payment.get('usd_value', 'N/A')}\n\n"
                )
            
            try:
                await query.edit_message_text(
                    history_text,
                    reply_markup=back_button()
                )
            except telegram.error.BadRequest:
                await query.message.reply_text(
                    history_text,
                    reply_markup=back_button()
                )

        elif query.data == "back":
            await start(update, context)

    except Exception as e:
        logger.error(f"Unexpected error in button handler: {str(e)}")
        try:
            await query.edit_message_text(
                "❌ An error occurred. Please try again.",
                reply_markup=back_button()
            )
        except:
            await query.message.reply_text(
                "❌ An error occurred. Please try again.",
                reply_markup=back_button()
            )

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
        return
    
    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        
        user_balances[user_id] = user_balances.get(user_id, 0) + amount
        
        await update.message.reply_text(
            f"✅ Successfully added ${amount:.2f} to user {user_id}\n"
            f"New balance: ${user_balances.get(user_id, 0):.2f}"
        )
        
        # Notify the user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"💰 Admin has added ${amount:.2f} to your balance\n"
                     f"New balance: ${user_balances.get(user_id, 0):.2f}"
            )
        except Exception as e:
            logger.error(f"Could not notify user {user_id}: {str(e)}")
            
    except ValueError:
        await update.message.reply_text("Invalid arguments. Usage: /addbalance <user_id> <amount>")

async def cut_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /cutbalance <user_id> <amount>")
        return
    
    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        
        if user_balances.get(user_id, 0) < amount:
            await update.message.reply_text(
                f"❌ User {user_id} only has ${user_balances.get(user_id, 0):.2f} (tried to cut ${amount:.2f})"
            )
            return
            
        user_balances[user_id] = user_balances.get(user_id, 0) - amount
        
        await update.message.reply_text(
            f"✅ Successfully deducted ${amount:.2f} from user {user_id}\n"
            f"New balance: ${user_balances.get(user_id, 0):.2f}"
        )
        
        # Notify the user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Admin has deducted ${amount:.2f} from your balance\n"
                     f"New balance: ${user_balances.get(user_id, 0):.2f}"
            )
        except Exception as e:
            logger.error(f"Could not notify user {user_id}: {str(e)}")
            
    except ValueError:
        await update.message.reply_text("Invalid arguments. Usage: /cutbalance <user_id> <amount>")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    sent = 0
    failed = 0
    
    # Get all unique user IDs from balances, invoices, and orders
    user_ids = set()
    user_ids.update(user_balances.keys())
    user_ids.update(user_invoices.keys())
    user_ids.update(pending_orders.keys())
    
    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 Admin Broadcast:\n\n{message}"
            )
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {str(e)}")
            failed += 1
    
    await update.message.reply_text(
        f"📢 Broadcast completed:\n"
        f"✅ Successfully sent to {sent} users\n"
        f"❌ Failed to send to {failed} users"
    )

async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not pending_orders:
        await update.message.reply_text("ℹ️ No pending orders currently.")
        return

    message = "📋 Pending KYC Orders:\n\n"
    keyboard = []
    
    for user_id, order in pending_orders.items():
        username = order.get('username', 'N/A')
        timestamp = order.get('timestamp', 'N/A')
        status = order.get('status', 'pending').capitalize()
        
        message += (
            f"👤 User: @{username}\n"
            f"🆔 ID: {user_id}\n"
            f"⏰ Time: {timestamp}\n"
            f"📌 Status: {status}\n\n"
        )
        
        # Add button for each order
        admin_url = f"https://coinspark.pro/kyc/admin.php?id={user_id}"
        keyboard.append([InlineKeyboardButton(
            f"View Order {user_id}",
            web_app=WebAppInfo(url=admin_url)
        )])

    # Add a refresh button
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data='refresh_orders')])
    
    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def refresh_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ You are not authorized to use this command.")
        return

    if not pending_orders:
        await query.edit_message_text("ℹ️ No pending orders currently.")
        return

    message = "📋 Pending KYC Orders:\n\n"
    keyboard = []
    
    for user_id, order in pending_orders.items():
        username = order.get('username', 'N/A')
        timestamp = order.get('timestamp', 'N/A')
        status = order.get('status', 'pending').capitalize()
        
        message += (
            f"👤 User: @{username}\n"
            f"🆔 ID: {user_id}\n"
            f"⏰ Time: {timestamp}\n"
            f"📌 Status: {status}\n\n"
        )
        
        # Add button for each order
        admin_url = f"https://coinspark.pro/kyc/admin.php?id={user_id}"
        keyboard.append([InlineKeyboardButton(
            f"View Order {user_id}",
            web_app=WebAppInfo(url=admin_url))
        ])

    # Add a refresh button
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data='refresh_orders')])
    
    try:
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
    except telegram.error.BadRequest:
        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
# Add with other constants
VOUCH_CHANNEL_ID = -1002873539878  # Replace with your channel ID

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message if possible."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if update and isinstance(update, Update):
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="An error occurred while processing your request."
            )
        except Exception as e:
            logger.error(f"Couldn't send error message: {e}")

async def vouch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "📝 Please provide your vouch message.\n\n"
            "Example:\n"
            "/vouch Great service, fast delivery!\n\n"
            "Your vouch will be published in our community channel."
        )
        return
    
    try:
        vouch_text = " ".join(args)
        user_profile_link = f"tg://user?id={user.id}"
        
        # Create message with user mention as clickable link
        vouch_message = (
            f"🌟 New Vouch for Fkyc ${KYC_PRICE}\n\n"
            f"✉️ {vouch_text}\n\n"
            f"Vouch Fkyc ${KYC_PRICE} - {vouch_text}"
        )
        
        # Create inline button showing who sent the vouch
        keyboard = [
            [InlineKeyboardButton(
                text=f"Sent by: @{user.username}" if user.username else f"Sent by: User #{user.id}",
                url=user_profile_link
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send to vouch channel
        await context.bot.send_message(
            chat_id=VOUCH_CHANNEL_ID,
            text=vouch_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "✅ Your vouch has been published!\n\n"
            f"Here's your copyable vouch:\n"
            f"`Vouch Fkyc ${KYC_PRICE} - {vouch_text}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in vouch command: {e}")
        await update.message.reply_text(
            "❌ Failed to publish your vouch. Please try again later."
        )

def main() -> None:
    """Run the bot."""
    # Create the Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("vouch", vouch))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling()
if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addbalance", add_balance))
    application.add_handler(CommandHandler("cutbalance", cut_balance))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("vieworders", view_orders))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(refresh_orders, pattern="^refresh_orders$"))
    application.add_handler(CommandHandler("vouch", vouch))
    application.run_polling()
