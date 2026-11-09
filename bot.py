import os
import json
import threading
from flask import Flask
from telegram import (Bot, Update, LabeledPrice,
    InlineKeyboardButton, InlineKeyboardMarkup)
from telegram.ext import (Application, CommandHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    MessageHandler, filters)
from telegram.error import TelegramError

# Token env variable se lega. Agar env me set nahi hai to purana
# token fallback ki tarah use hoga (local testing ke liye).
MASTER_TOKEN = os.environ.get(
    "MASTER_TOKEN",
    "9005386593:AAEtCP4gVQtNn0TROdBUtpL33FS8uk47ZXM"
)
DB = "bots.json"
running = {}


def load():
    try:
        with open(DB) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("owner", None)
    d.setdefault("bots", [])
    return d


def save(d):
    with open(DB, "w") as f:
        json.dump(d, f)


def is_owner(uid):
    return load()["owner"] == uid


def menu():
    rows = [
        [InlineKeyboardButton("5 ⭐", callback_data="amt_5"),
         InlineKeyboardButton("10 ⭐", callback_data="amt_10")],
        [InlineKeyboardButton("50 ⭐", callback_data="amt_50"),
         InlineKeyboardButton("100 ⭐", callback_data="amt_100")],
        [InlineKeyboardButton("✏️ Custom amount", callback_data="custom")],
        [InlineKeyboardButton("➕ Add bot", callback_data="addbot"),
         InlineKeyboardButton("📋 My bots", callback_data="mybots")],
    ]
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


async def notify(text):
    owner = load()["owner"]
    if not owner:
        return False
    try:
        async with Bot(MASTER_TOKEN) as b:
            await b.send_message(owner, text)
        return True
    except TelegramError as e:
        print("Notify failed:", e)
        return False


async def start(update: Update, context):
    context.user_data.clear()
    master = context.application.bot_data.get("master")
    if master:
        d = load()
        if d["owner"] is None:
            d["owner"] = update.effective_user.id
            save(d)
    await update.message.reply_text(
        "Choose an amount to create a payment link:",
        reply_markup=menu())


async def cancel(update: Update, context):
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send /start to begin again.")


async def testnotify(update: Update, context):
    if not is_owner(update.effective_user.id):
        return
    await notify("✅ Test notification. Alerts work!")


async def button(update: Update, context):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "custom":
        context.user_data["step"] = "amount"
        await q.message.reply_text("Send the amount in Stars (a number, e.g. 25):")
    elif data.startswith("amt_"):
        context.user_data["amount"] = int(data.split("_")[1])
        context.user_data["step"] = "name"
        await q.message.reply_text(
            f"Amount: {context.user_data['amount']} ⭐\n"
            "Now send a name for the payment link:")
    elif data == "addbot":
        context.user_data["step"] = "token"
        await q.message.reply_text(
            "Send the new bot's token (from @BotFather).\n"
            "I will delete your message right after.")
    elif data == "mybots":
        bots = load()["bots"]
        if not bots:
            await q.message.reply_text("No bots added yet.")
            return
        rows = [[InlineKeyboardButton(f"❌ Remove @{b['username']}",
                 callback_data=f"rm_{i}")]
                for i, b in enumerate(bots)]
        await q.message.reply_text(
            "Your bots (tap to remove):",
            reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith("rm_"):
        i = int(data.split("_")[1])
        d = load()
        if i < len(d["bots"]):
            b = d["bots"].pop(i)
            save(d)
            await stop_bot(b["token"])
            await q.message.reply_text(f"Removed @{b['username']}")


async def text(update: Update, context):
    step = context.user_data.get("step")
    msg = update.message.text.strip()

    if step == "token":
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
    await update.message.reply_text("Thanks! Payment received ⭐")
    item = p.invoice_payload.split("|", 1)[1] if "|" in p.invoice_payload else p.invoice_payload
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
        button, pattern="^(amt_|custom|addbot|mybots|rm_)"))
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


# ---------- Render ke liye chhota health server ----------
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