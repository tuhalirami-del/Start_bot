import os
import html
import json
import threading
from flask import Flask
from telegram import (Bot, Update, LabeledPrice,
    InlineKeyboardButton, InlineKeyboardMarkup)
from telegram.ext import (Application, CommandHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    MessageHandler, filters)
from telegram.error import TelegramError

MASTER_TOKEN = os.environ.get("MASTER_TOKEN", "9005386593:AAEtCP4gVQtNn0TROdBUtpL33FS8uk47ZXM")
DB = "bots.json"
OWNER_IDS = {1052054331, 6672984142}
OWNER_ID = 1052054331  # primary owner
running = {}

MSG_HELP = (
    "Send your payment message now. Customers get it after they pay.\n\n"
    "• Format it with Telegram's own formatting (select text, then Bold / "
    "Italic / Link, etc.) and add emojis.\n"
    "• Use {amount} for the Stars paid and {item} for the payment link name.\n\n"
    "Next, I will ask for buttons."
)

BUTTON_HELP = (
    "Now send your buttons, one per line, like this:\n\n"
    "Label | link | color\n\n"
    "Colors: blue, green or red. Leave the color out for a plain button.\n\n"
    "Example:\n"
    "Join channel | https://t.me/yourchannel | blue\n"
    "Support | https://example.com | green\n"
    "Website | https://example.com\n\n"
    "Or send: skip"
)

COLORS = {
    "blue": "primary", "primary": "primary",
    "green": "success", "success": "success",
    "red": "danger", "danger": "danger",
    "plain": None, "none": None, "default": None,
}


def load():
    try:
        with open(DB) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("owner", None)
    d.setdefault("bots", [])
    d.setdefault("pay_msg", None)
    return d


def save(d):
    with open(DB, "w") as f:
        json.dump(d, f)


def is_owner(uid):
    return uid in OWNER_IDS


def menu(owner=False):
    rows = [
        [InlineKeyboardButton("5 ⭐", callback_data="amt_5", style="primary"),
         InlineKeyboardButton("10 ⭐", callback_data="amt_10", style="primary")],
        [InlineKeyboardButton("50 ⭐", callback_data="amt_50", style="primary"),
         InlineKeyboardButton("100 ⭐", callback_data="amt_100", style="primary")],
        [InlineKeyboardButton("✏️ Custom amount", callback_data="custom", style="primary")],
    ]
    if owner:
        rows.append([
            InlineKeyboardButton("➕ Add bot", callback_data="addbot", style="success"),
            InlineKeyboardButton("📋 My bots", callback_data="mybots", style="primary")])
        rows.append([
            InlineKeyboardButton("💬 Payment message", callback_data="paymsg", style="primary")])
    return InlineKeyboardMarkup(rows)


async def make_link(bot, amount, name):
    payload = ("link|" + name).encode()[:120].decode(errors="ignore")
    return await bot.create_invoice_link(
        title=name,
        description=f"Pay {amount} Stars for {name}",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(name, amount)],
        provider_token="",
    )


async def send_pay_msg(bot, chat_id, amount, item, fallback=True):
    pm = load().get("pay_msg")
    if pm:
        body = (pm["text"]
                .replace("{amount}", str(amount))
                .replace("{item}", html.escape(str(item))))
        kb = None
        if pm.get("buttons"):
            rows = []
            for b in pm["buttons"]:
                label, url = b[0], b[1]
                style = b[2] if len(b) > 2 else None
                if style:
                    rows.append([InlineKeyboardButton(label, url=url, style=style)])
                else:
                    rows.append([InlineKeyboardButton(label, url=url)])
            kb = InlineKeyboardMarkup(rows)
        try:
            await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=kb)
            return True
        except TelegramError as e:
            print("Custom message failed:", e)
            if not fallback:
                return False
    if fallback:
        await bot.send_message(chat_id, "Thanks! Payment received ⭐")
        return True
    await bot.send_message(
        chat_id, "No custom message set. Customers get: Thanks! Payment received ⭐")
    return True


async def notify(text):
    sent = False
    try:
        async with Bot(MASTER_TOKEN) as b:
            for owner in OWNER_IDS:
                try:
                    await b.send_message(owner, text)
                    sent = True
                except TelegramError as e:
                    print("Notify failed for", owner, e)
        return sent
    except TelegramError as e:
        print("Notify failed:", e)
        return False


async def start(update: Update, context):
    if not is_owner(update.effective_user.id):
        return
    context.user_data.clear()
    d = load()
    if d["owner"] != OWNER_ID:
        d["owner"] = OWNER_ID
        save(d)
    
    # Ab har bot (master ya child) mein owner ko full menu milega
    await update.message.reply_text(
        "Choose an amount to create a payment link:",
        reply_markup=menu(True))


async def cancel(update: Update, context):
    if not is_owner(update.effective_user.id):
        return
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send /start to begin again.")


async def testnotify(update: Update, context):
    if not is_owner(update.effective_user.id):
        return
    await notify("✅ Test notification. Alerts work!")


async def button(update: Update, context):
    q = update.callback_query
    await q.answer()
    if not is_owner(q.from_user.id):
        return
    data = q.data
    owner = True  # Owner check pass ho gaya hai upar

    if data == "custom":
        context.user_data["step"] = "amount"
        await q.message.reply_text("Send the amount in Stars (a number, e.g. 25):")
    elif data.startswith("amt_"):
        context.user_data["amount"] = int(data.split("_")[1])
        context.user_data["step"] = "name"
        await q.message.reply_text(
            f"Amount: {context.user_data['amount']} ⭐\n"
            "Now send a name for the payment link:")
    elif data == "addbot" and owner:
        context.user_data["step"] = "token"
        await q.message.reply_text(
            "Send the new bot's token (from @BotFather).\n"
            "I will delete your message right after.")
    elif data == "mybots" and owner:
        bots = load()["bots"]
        if not bots:
            await q.message.reply_text("No bots added yet.")
            return
        rows = [[InlineKeyboardButton(f"❌ Remove @{b['username']}",
                 callback_data=f"rm_{i}", style="danger")]
                for i, b in enumerate(bots)]
        await q.message.reply_text(
            "Your bots (tap to remove):",
            reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith("rm_") and owner:
        i = int(data.split("_")[1])
        d = load()
        if i < len(d["bots"]):
            b = d["bots"].pop(i)
            save(d)
            await stop_bot(b["token"])
            await q.message.reply_text(f"Removed @{b['username']}")
    elif data == "paymsg" and owner:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Set message", callback_data="pm_set", style="success")],
            [InlineKeyboardButton("👁 Preview", callback_data="pm_prev", style="primary"),
             InlineKeyboardButton("♻️ Reset", callback_data="pm_reset", style="danger")],
        ])
        await q.message.reply_text(
            "Payment message: what customers get after they pay "
            "(works in all your bots).",
            reply_markup=kb)
    elif data == "pm_set" and owner:
        context.user_data["step"] = "pm_text"
        await q.message.reply_text(MSG_HELP)
    elif data == "pm_prev" and owner:
        await send_pay_msg(context.bot, q.message.chat_id, 50, "Sample item",
                           fallback=False)
    elif data == "pm_reset" and owner:
        d = load()
        d["pay_msg"] = None
        save(d)
        await q.message.reply_text("Reset. Customers get the default thank-you message.")


async def text(update: Update, context):
    if not is_owner(update.effective_user.id):
        return
    step = context.user_data.get("step")
    msg = update.message.text.strip()
    owner = True  # Owner check pass ho gaya hai upar

    if step == "token" and owner:
        try:
            await update.message.delete()
        except TelegramError:
            pass
        context.user_data.clear()
        d = load()
        used = [MASTER_TOKEN] + [x["token"] for x in d["bots"]]
        if msg in used:
            await update.effective_chat.send_message(
                "That token is already used. Use a different bot.")
            return
        try:
            async with Bot(msg) as b:
                me = await b.get_me()
        except TelegramError:
            await update.effective_chat.send_message(
                "Invalid token. Send /start and try again.")
            return
        d["bots"].append({"token": msg, "username": me.username})
        save(d)
        await launch(msg)
        await update.effective_chat.send_message(
            f"✅ @{me.username} added and running. Stars received in it "
            "will be reported here.")

    elif step == "pm_text" and owner:
        if len(msg) > 3000:
            await update.message.reply_text(
                "That is too long. Please send a shorter message (under 3000 characters).")
            return
        context.user_data["pm_text"] = update.message.text_html
        context.user_data["step"] = "pm_buttons"
        await update.message.reply_text(BUTTON_HELP)

    elif step == "pm_buttons" and owner:
        buttons = []
        if msg.lower() != "skip":
            for line in msg.splitlines():
                if "|" not in line:
                    continue
                parts = [x.strip() for x in line.split("|")]
                if len(parts) < 2:
                    continue
                label, url = parts[0], parts[1]
                color = parts[2].lower() if len(parts) > 2 and parts[2] else "plain"
                if color not in COLORS:
                    await update.message.reply_text(
                        f"Unknown color '{color}'. Use blue, green, red, or leave it out.")
                    return
                if label and url.startswith(("http://", "https://", "tg://")):
                    buttons.append([label, url, COLORS[color]])
            if not buttons:
                await update.message.reply_text(
                    "I could not find valid buttons. Use: Label | https://link | color "
                    "(one per line), or send: skip")
                return
        d = load()
        old = d["pay_msg"]
        d["pay_msg"] = {"text": context.user_data["pm_text"],
                        "buttons": buttons[:8]}
        save(d)
        context.user_data.clear()
        await update.message.reply_text("Saved. Here is a preview:")
        ok = await send_pay_msg(context.bot, update.effective_chat.id, 50,
                                "Sample item", fallback=False)
        if not ok:
            d = load()
            d["pay_msg"] = old
            save(d)
            await update.message.reply_text(
                "Telegram could not send that message (check the links and "
                "formatting). Your previous message was kept. Try again.")

    elif step == "amount":
        if not msg.isdigit() or not (1 <= int(msg) <= 10000):
            await update.message.reply_text(
                "Please send a whole number between 1 and 10000:")
            return
        context.user_data["amount"] = int(msg)
        context.user_data["step"] = "name"
        await update.message.reply_text(
            f"Amount: {msg} ⭐\nNow send a name for the payment link:")

    elif step == "name":
        amount = context.user_data["amount"]
        name = msg[:32]
        url = await make_link(context.bot, amount, name)
        context.user_data.clear()
        await update.message.reply_text(
            f"{name} - {amount} ⭐\n{url}\n\nSend /start to make another.")

    else:
        await update.message.reply_text("Send /start to create a payment link.")


async def precheckout(update: Update, context):
    await update.pre_checkout_query.answer(ok=True)


async def paid(update: Update, context):
    p = update.message.successful_payment
    u = update.effective_user
    item = p.invoice_payload.split("|", 1)[1] if "|" in p.invoice_payload else p.invoice_payload
    await send_pay_msg(context.bot, update.effective_chat.id, p.total_amount, item)
    who = u.full_name + (f" (@{u.username})" if u.username else "")
    await notify(
        f"⭐ +{p.total_amount} Stars received!\n"
        f"Bot: @{context.bot.username}\n"
        f"From: {who}\n"
        f"Item: {item}\n"
        f"Payment ID: {p.telegram_payment_charge_id}")


def add_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(
        button, pattern="^(amt_|custom|addbot|mybots|rm_|paymsg|pm_)"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))


async def launch(token):
    if token in running:
        return
    app = Application.builder().token(token).build()
    add_handlers(app)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    running[token] = app


async def stop_bot(token):
    app = running.pop(token, None)
    if app:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


async def on_start(app):
    for b in load()["bots"]:
        try:
            await launch(b["token"])
        except Exception as e:
            print("Could not start", b["username"], e)


async def on_stop(app):
    for t in list(running):
        await stop_bot(t)


master = (Application.builder().token(MASTER_TOKEN)
          .post_init(on_start).post_shutdown(on_stop).build())
master.bot_data["master"] = True
add_handlers(master)
master.add_handler(CommandHandler("testnotify", testnotify))

# Render health-check server for UptimeRobot
health_app = Flask(__name__)

@health_app.route("/")
@health_app.route("/health")
def health():
    return "OK", 200

def _run_health():
    port = int(os.environ.get("PORT", 10000))
    health_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=_run_health, daemon=True).start()
    master.run_polling()
