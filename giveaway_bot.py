# giveaway_bot.py
import asyncio, json, os, random
from typing import Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

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

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def admin_keyboard(state: Dict[str, Any]) -> InlineKeyboardMarkup:
    active = state["active"]
    buttons = [
        [InlineKeyboardButton("Start Giveaway ✅", callback_data="admin:start")],
        [InlineKeyboardButton("End Giveaway ⛔", callback_data="admin:end")],
        [InlineKeyboardButton("Pick Random 🎲", callback_data="admin:pick_random")],
        [InlineKeyboardButton("Pick Specific 🎯", callback_data="admin:pick_specific")],
        [InlineKeyboardButton("Show Entries 📋", callback_data="admin:show_entries")],
        [InlineKeyboardButton("Show Winners 🏆", callback_data="admin:show_winners")],
    ]
    # Subtle UX hint by enabling/disabling visually through label; functional gating happens server-side
    if active:
        buttons[0][0].text = "Start Giveaway ✅ (Active)"
    else:
        buttons[1][0].text = "End Giveaway ⛔ (Inactive)"
    return InlineKeyboardMarkup(buttons)

def user_keyboard(state: Dict[str, Any]) -> InlineKeyboardMarkup:
    if state["active"]:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Click to Enter Giveaway", callback_data="user:enter")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏸️ Giveaway not active", callback_data="noop")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with LOCK:
        s = _load()
    text = "Welcome! Tap below to enter the current giveaway." if s["active"] else "No active giveaway right now."
    kb = user_keyboard(s)
    await update.message.reply_text(text, reply_markup=kb)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
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
        await query.edit_message_text(f"You're in! Your entry number is #{number}. Good luck! 🎉")
        return

    if data.startswith("admin:"):
        if not is_admin(user.id):
            return await query.edit_message_text("Unauthorized.")
        cmd = data.split(":",1)[1]
        async with LOCK:
            s = _load()
            if cmd == "start":
                s["active"] = True
                s["entries"] = []
                _save(s)
                return await query.edit_message_text("Giveaway started. Entries cleared.", reply_markup=admin_keyboard(s))
            if cmd == "end":
                s["active"] = False
                _save(s)
                return await query.edit_message_text("Giveaway ended.", reply_markup=admin_keyboard(s))
            if cmd == "pick_random":
                if not s["entries"]:
                    return await query.edit_message_text("No entries to pick from.", reply_markup=admin_keyboard(s))
                winner = random.choice(s["entries"])
                s["entries"] = [e for e in s["entries"] if e["user_id"] != winner["user_id"]]
                s["winners"].append(winner)
                _save(s)
                ulabel = winner.get("username") and f"@{winner['username']}" or f"{winner.get('first_name','')} {winner.get('last_name','')}".strip()
                return await query.edit_message_text(f"Winner: {ulabel} (id {winner['user_id']}) 🏆\nRemoved from current pool.", reply_markup=admin_keyboard(s))
            if cmd == "pick_specific":
                _save(s)
        await query.edit_message_text("Reply with a user ID to pick (or @username).", reply_markup=None)
        context.user_data["awaiting_specific"] = True
        return
    # Fallback
    await query.edit_message_text("Unknown action.")

async def pick_specific_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_specific"):
        return
    text = (update.message.text or "").strip()
    target_id = None
    by_username = None
    if text.startswith("@"):
        by_username = text[1:].lower()
    else:
        if text.isdigit():
            target_id = int(text)

    async with LOCK:
        s = _load()
        if by_username:
            cand = [e for e in s["entries"] if (e.get("username") or "").lower() == by_username]
            if not cand:
                await update.message.reply_text(f"No entry for @{by_username}.")
                context.user_data["awaiting_specific"] = False
                return
            winner = cand[0]
        else:
            cand = [e for e in s["entries"] if e["user_id"] == target_id]
            if not cand:
                await update.message.reply_text(f"No entry for id {target_id}.")
                context.user_data["awaiting_specific"] = False
                return
            winner = cand[0]
        s["entries"] = [e for e in s["entries"] if e["user_id"] != winner["user_id"]]
        s["winners"].append(winner)
        _save(s)

    ulabel = winner.get("username") and f"@{winner['username']}" or f"{winner.get('first_name','')} {winner.get('last_name','')}".strip()
    await update.message.reply_text(f"Winner: {ulabel} (id {winner['user_id']}) 🏆\nRemoved from current pool.")
    context.user_data["awaiting_specific"] = False

async def show_entries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("Unauthorized.")
    cmd = (update.message.text or "").strip().lower()
    if cmd == "/admin":
        async with LOCK:
            s = _load()
        return await update.message.reply_text("Admin Panel", reply_markup=admin_keyboard(s))
    if cmd == "/show_entries":
        return await show_entries(update, context)
    if cmd == "/show_winners":
        return await show_winners(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), admin_panel_shortcuts))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), pick_specific_text))
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    if TOKEN == "PUT_YOUR_TOKEN_HERE" or not TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var or hardcode TOKEN.")
    main()
