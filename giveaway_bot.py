ADMIN_GROUPS_FILE = "admin_groups.json"

def _load_admin_groups() -> dict:
    if not os.path.exists(ADMIN_GROUPS_FILE):
        return {}
    try:
        with open(ADMIN_GROUPS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _save_admin_group(user_id: int, group_id: int):
    groups = _load_admin_groups()
    groups[str(user_id)] = group_id
    with open(ADMIN_GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f)
# Move async def set_announce_interval below imports
# giveaway_bot.py
import asyncio, json, os, random
from typing import Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)
async def set_announce_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Only allow in private chat
    if update.effective_chat.type != "private":
        return await update.message.reply_text("Please use this command in a private chat with the bot.")
    if not await is_admin(user.id, update, context):
        return await update.message.reply_text("Unauthorized.")
    args = context.args
    if not args or not args[0].isdigit():
        return await update.message.reply_text("Usage: /gset_announce_interval <minutes>")
    minutes = int(args[0])
    if minutes < 1:
        return await update.message.reply_text("Interval must be at least 1 minute.")
    _save_announce_interval(minutes)
    await update.message.reply_text(f"Announcement interval set to {minutes} minutes.")
ANNOUNCE_INTERVAL_FILE = "announce_interval.json"

def _load_announce_interval() -> int:
    if not os.path.exists(ANNOUNCE_INTERVAL_FILE):
        return 10  # default 10 minutes
    try:
        with open(ANNOUNCE_INTERVAL_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("interval", 10))
    except:
        return 10

def _save_announce_interval(interval: int) -> None:
    with open(ANNOUNCE_INTERVAL_FILE, "w", encoding="utf-8") as f:
        json.dump({"interval": interval}, f)



TOKEN = "PUT_YOUR_TOKEN_HERE"

ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()}
STATE_FILE = "giveaway.json"

LOCK = asyncio.Lock()
PICK_SPECIFIC = 1

def _blank_state() -> Dict[str, Any]:
    return {"active": False, "entries": [], "winners": []}

def _load() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE): return _blank_state()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
            for k in ["active","entries","winners"]:
                if k not in s: s[k] = _blank_state()[k]
            return s
    except:
        return _blank_state()

def _save(state: Dict[str, Any]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

from telegram.constants import ChatMemberStatus

async def is_admin(user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup"]:
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            for member in admins:
                if member.user.id == user_id:
                    if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                        return True
            return False
        except Exception as e:
            print(f"[WARN] Could not fetch chat admins: {e}")
            return user_id in ADMIN_IDS
    # Private chat: check if user is mapped to a group
    groups = _load_admin_groups()
    if str(user_id) in groups:
        return True
    return user_id in ADMIN_IDS

def admin_keyboard(state: Dict[str, Any]) -> InlineKeyboardMarkup:
    active = state["active"]
    buttons = []
    if not active:
        buttons.append([InlineKeyboardButton("Start Giveaway ✅", callback_data="admin:start")])
    else:
        buttons.append([InlineKeyboardButton("End Giveaway ⛔", callback_data="admin:end")])
    buttons.append([InlineKeyboardButton("Pick Random 🎲", callback_data="admin:pick_random")])
    buttons.append([InlineKeyboardButton("Show Entries 📋", callback_data="admin:show_entries")])
    buttons.append([InlineKeyboardButton("Show Winners 🏆", callback_data="admin:show_winners")])
    buttons.append([InlineKeyboardButton("Clear Winners 🧹", callback_data="admin:clear_winners")])
    buttons.append([InlineKeyboardButton("Set Announcement Interval ⏰", callback_data="admin:set_announce_interval")])
    return InlineKeyboardMarkup(buttons)

async def user_keyboard(state: Dict[str, Any], update: Update, context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    buttons = []
    if state["active"]:
        buttons.append([InlineKeyboardButton("🎁 Click to Enter Giveaway", callback_data="user:enter")])
        buttons.append([InlineKeyboardButton("❓ Help", callback_data="user:help")])
        user = update.effective_user
        if await is_admin(user.id, update, context):
            buttons.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="user:admin")])
    else:
        buttons.append([InlineKeyboardButton("⏸️ Giveaway not active", callback_data="noop")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with LOCK:
        s = _load()
    text = "Welcome! Tap below to enter the current giveaway." if s["active"] else "No active giveaway right now."
    kb = await user_keyboard(s, update, context)
    await update.message.reply_text(text, reply_markup=kb)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup"]:
        # Link admin to group
        groups = _load_admin_groups()
        already_admin = str(user.id) in groups and groups[str(user.id)] == chat.id
        if not already_admin:
            _save_admin_group(user.id, chat.id)
            return await update.message.reply_text("You’ve been added as a giveaway admin for this group!")
        else:
            return await update.message.reply_text("You’re already a giveaway admin for this group!")
    # Private chat: show admin panel
    if not await is_admin(user.id, update, context):
        return await update.message.reply_text("Unauthorized.")
    async with LOCK:
        s = _load()
    await update.message.reply_text("Admin Panel", reply_markup=admin_keyboard(s))

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data or ""
    await query.answer()

    if data == "noop":
        return

    if data == "user:help":
        help_text = "Help: To become an admin, use /giveaway or /gstart in your group chat as a group admin. Then DM this bot to access admin features."
        await query.edit_message_text(help_text)
        return

    if data == "user:admin":
        async with LOCK:
            s = _load()
        await query.edit_message_text("Admin Panel", reply_markup=admin_keyboard(s))
        return

    if data.startswith("user:"):
        async with LOCK:
            s = _load()
            if not s["active"]:
                return await query.edit_message_text("No active giveaway right now.")
            uid = user.id
            if any(e["user_id"] == uid for e in s["entries"]):
                idx = next(i for i,e in enumerate(s["entries"], start=1) if e["user_id"] == uid)
                return await query.edit_message_text(f"You're already entered. Your number is #{idx}.")
            entry = {"user_id": uid, "username": user.username or "", "first_name": user.first_name or "", "last_name": user.last_name or ""}
            s["entries"].append(entry)
            _save(s)
            number = len(s["entries"])
            print(f"[INFO] User entered giveaway: id={uid}, username={user.username}, entry number={number}")
        await query.edit_message_text(f"You're in! Your entry number is #{number}. Good luck! 🎉")
        return

    if data.startswith("admin:"):
        if not await is_admin(user.id, update, context):
            return await query.edit_message_text("Unauthorized.")
        cmd = data.split(":",1)[1]
        async with LOCK:
            s = _load()
            if cmd == "start":
                s["active"] = True
                s["entries"] = []
                _save(s)
                print("[INFO] Giveaway started. Entries cleared.")
                # If in private chat, announce to associated group
                if update.effective_chat.type == "private":
                    groups = _load_admin_groups()
                    group_id = groups.get(str(user.id))
                    if group_id:
                        bot_username = (await context.bot.get_me()).username
                        await context.bot.send_message(
                            chat_id=group_id,
                            text="A giveaway has started! Use /start in private chat with the bot to enter.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("DM the Bot", url=f"https://t.me/{bot_username}")]
                            ])
                        )
                return await query.edit_message_text("Giveaway started. Entries cleared.", reply_markup=admin_keyboard(s))
            if cmd == "end":
                s["active"] = False
                _save(s)
                print("[INFO] Giveaway ended.")
                return await query.edit_message_text("Giveaway ended.", reply_markup=admin_keyboard(s))
            if cmd == "pick_random":
                if not s["entries"]:
                    return await query.edit_message_text("No entries to pick from.", reply_markup=admin_keyboard(s))
                winner = random.choice(s["entries"])
                s["entries"] = [e for e in s["entries"] if e["user_id"] != winner["user_id"]]
                s["winners"].append(winner)
                _save(s)
                ulabel = winner.get("username") and f"@{winner['username']}" or f"{winner.get('first_name','')} {winner.get('last_name','')}".strip()
                print(f"[INFO] Random winner picked: {ulabel} (id {winner['user_id']})")
                # Send winner announcement to group if in private chat
                if update.effective_chat.type == "private":
                    groups = _load_admin_groups()
                    group_id = groups.get(str(user.id))
                    if group_id:
                        bot_username = (await context.bot.get_me()).username
                        await context.bot.send_message(
                            chat_id=group_id,
                            text=f"🎉 Giveaway Winner: {ulabel} (id {winner['user_id']})",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("DM the Bot", url=f"https://t.me/{bot_username}")]
                            ])
                        )
                return await query.edit_message_text(f"Winner: {ulabel} (id {winner['user_id']}) 🏆\nRemoved from current pool.", reply_markup=admin_keyboard(s))
            # Pick Specific removed
            if cmd == "clear_winners":
                s["winners"] = []
                _save(s)
                print("[INFO] Winners list cleared.")
                return await query.edit_message_text("Winners list cleared.", reply_markup=admin_keyboard(s))
    # Fallback
    await query.edit_message_text("Unknown action.")

    # Pick Specific feature removed

async def show_entries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, update, context):
        return await update.message.reply_text("Unauthorized.")
    async with LOCK:
        s = _load()
        entries = s["entries"]
    if not entries:
        return await update.message.reply_text("Entries: (none)")
    lines = []
    for i, e in enumerate(entries, start=1):
        tag = f"@{e['username']}" if e.get("username") else f"{e.get('first_name','')} {e.get('last_name','')}".strip()
        lines.append(f"#{i} - {tag} (id {e['user_id']})")
    await update.message.reply_text("Entries:\n" + "\n".join(lines))

async def show_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, update, context):
        return await update.message.reply_text("Unauthorized.")
    async with LOCK:
        s = _load()
        winners = s["winners"]
    if not winners:
        return await update.message.reply_text("Winners: (none)")
    lines = []
    for i, e in enumerate(winners, start=1):
        tag = f"@{e['username']}" if e.get("username") else f"{e.get('first_name','')} {e.get('last_name','')}".strip()
        lines.append(f"{i}. {tag} (id {e['user_id']})")
    await update.message.reply_text("Winners:\n" + "\n".join(lines))

async def admin_panel_shortcuts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Optional text commands for admins
    if not await is_admin(update.effective_user.id, update, context):
        return await update.message.reply_text("Unauthorized.")
    cmd = (update.message.text or "").strip().lower()
    if cmd == "/gshow_entries":
        return await show_entries(update, context)
    if cmd == "/gshow_winners":
        return await show_winners(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    async def group_giveaway_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user
        if chat and chat.type in ["group", "supergroup"]:
            # Add to admin list if user is admin
            if await is_admin(user.id, update, context):
                groups = _load_admin_groups()
                already_admin = str(user.id) in groups and groups[str(user.id)] == chat.id
                if not already_admin:
                    _save_admin_group(user.id, chat.id)
            bot_username = (await context.bot.get_me()).username
            await update.message.reply_text(
                "To enter the giveaway, DM this bot and use /start.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("DM the Bot", url=f"https://t.me/{bot_username}")]
                ])
            )
        else:
            await start(update, context)
    app.add_handler(CommandHandler("gstart", group_giveaway_entry))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("giveaway", group_giveaway_entry))
    app.add_handler(CommandHandler("gset_announce_interval", set_announce_interval))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), admin_panel_shortcuts))

    # Regular announcements
    async def announce_giveaway_periodically(app):
        while True:
            await asyncio.sleep(_load_announce_interval() * 60)
            s = _load()
            if s["active"]:
                groups = _load_admin_groups()
                for group_id in set(groups.values()):
                    bot_username = (await app.bot.get_me()).username
                    await app.bot.send_message(
                        chat_id=group_id,
                        text="A giveaway is active! DM this bot and use /start to enter.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("DM the Bot", url=f"https://t.me/{bot_username}")]
                        ])
                    )

    async def run_announcer():
        await announce_giveaway_periodically(app)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.create_task(run_announcer())
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    if TOKEN == "PUT_YOUR_TOKEN_HERE" or not TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var or hardcode TOKEN.")
    main()
