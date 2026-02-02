import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN na Render")

# ================= KEEP ALIVE =================

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Financeiro ativo!")

def run_keep_alive():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), KeepAliveHandler).serve_forever()

threading.Thread(target=run_keep_alive, daemon=True).start()

# ================= DATABASE =================

conn = sqlite3.connect("finance.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    type TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount REAL,
    category TEXT,
    description TEXT,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS incomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    value REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS fixed_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    value REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    limit_value REAL
)
""")

conn.commit()

# ================= MEMORY =================
user_state = {}

# ================= HELPERS =================

def init_user(tid):
    cur.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (tid,))
    conn.commit()

def get_categories(uid, ctype):
    cur.execute("SELECT name FROM categories WHERE user_id=? AND type=?", (uid, ctype))
    return [x[0] for x in cur.fetchall()]

def add_category(uid, name, ctype):
    cur.execute("INSERT INTO categories (user_id, name, type) VALUES (?, ?, ?)", (uid, name, ctype))
    conn.commit()

def add_transaction(uid, t, amount, cat, desc):
    cur.execute("""
        INSERT INTO transactions (user_id, type, amount, category, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (uid, t, amount, cat, desc, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()

# ================= MENU =================

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📉 Novo Gasto", callback_data="gasto"),
         InlineKeyboardButton("📈 Novo Ganho", callback_data="ganho")],

        [InlineKeyboardButton("🏷️ Nova Categoria", callback_data="newcat"),
         InlineKeyboardButton("💼 Registrar Renda", callback_data="addrenda")],

        [InlineKeyboardButton("📦 Custo Fixo", callback_data="fixo"),
         InlineKeyboardButton("🎯 Definir Meta", callback_data="meta")],

        [InlineKeyboardButton("📊 Análise Completa", callback_data="analise")],
        [InlineKeyboardButton("📋 Histórico", callback_data="historico")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_user(update.effective_user.id)
    await update.message.reply_text("🤖 Controle Financeiro Premium", reply_markup=menu())

# ================= GASTO / GANHO =================

async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"type": "expense", "step": "value"}
    await update.callback_query.edit_message_text("💰 Digite o valor do gasto:")

async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"type": "income", "step": "value"}
    await update.callback_query.edit_message_text("💰 Digite o valor do ganho:")

async def receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "value":
        return

    try:
        val = float(update.message.text.replace(",", "."))
        user_state[uid]["value"] = val
        user_state[uid]["step"] = "category"
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return

    ctype = user_state[uid]["type"]
    cats = get_categories(uid, ctype)

    if not cats:
        await update.message.reply_text("⚠️ Cadastre uma categoria primeiro!")
        del user_state[uid]
        return

    buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
    await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    if uid not in user_state:
        return

    user_state[uid]["category"] = update.callback_query.data.replace("cat_", "")
    user_state[uid]["step"] = "desc"

    await update.callback_query.edit_message_text("📝 Digite a descrição:")

async def receive_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "desc":
        return

    data = user_state[uid]
    add_transaction(uid, data["type"], data["value"], data["category"], update.message.text)

    del user_state[uid]
    await update.message.reply_text("✅ Registro salvo!", reply_markup=menu())

# ================= ADD CATEGORY FIXED =================

async def new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "newcat"}
    await update.callback_query.edit_message_text("🏷️ Digite o nome da nova categoria:")

async def save_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "newcat":
        return

    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text("❌ Nome inválido. Digite outro:")
        return

    cur.execute("SELECT name FROM categories WHERE user_id=? AND name=?", (uid, name))
    if cur.fetchone():
        await update.message.reply_text("⚠️ Categoria já existe. Digite outro nome:")
        return

    user_state[uid]["name"] = name

    buttons = [
        [InlineKeyboardButton("📉 Categoria de GASTO", callback_data="type_expense")],
        [InlineKeyboardButton("📈 Categoria de GANHO", callback_data="type_income")]
    ]

    await update.message.reply_text("Selecione o tipo:", reply_markup=InlineKeyboardMarkup(buttons))

async def save_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    if uid not in user_state or "name" not in user_state[uid]:
        return

    ctype = "expense" if update.callback_query.data == "type_expense" else "income"
    name = user_state[uid]["name"]

    add_category(uid, name, ctype)

    del user_state[uid]
    await update.callback_query.edit_message_text(f"✅ Categoria criada: {name}", reply_markup=menu())

# ================= RENDA =================

async def renda_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "renda"}
    await update.callback_query.edit_message_text("💼 Nome da renda:")

async def renda_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "renda":
        return

    user_state[uid]["name"] = update.message.text
    await update.message.reply_text("💰 Valor da renda:")

async def renda_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "renda":
        return

    val = float(update.message.text.replace(",", "."))

    cur.execute("INSERT INTO incomes (user_id, name, value) VALUES (?, ?, ?)",
                (uid, user_state[uid]["name"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("✅ Renda salva!", reply_markup=menu())

# ================= CUSTO FIXO =================

async def fixed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "fixo"}
    await update.callback_query.edit_message_text("📦 Nome do custo fixo:")

async def fixed_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "fixo":
        return

    user_state[uid]["name"] = update.message.text
    await update.message.reply_text("💰 Valor do custo:")

async def fixed_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "fixo":
        return

    val = float(update.message.text.replace(",", "."))

    cur.execute("INSERT INTO fixed_costs (user_id, name, value) VALUES (?, ?, ?)",
                (uid, user_state[uid]["name"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("✅ Custo fixo salvo!", reply_markup=menu())

# ================= META =================

async def meta_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "meta"}
    await update.callback_query.edit_message_text("🎯 Nome da categoria da meta:")

async def meta_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "meta":
        return

    user_state[uid]["category"] = update.message.text
    await update.message.reply_text("💰 Valor limite:")

async def meta_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "meta":
        return

    val = float(update.message.text.replace(",", "."))

    cur.execute("INSERT INTO goals (user_id, category, limit_value) VALUES (?, ?, ?)",
                (uid, user_state[uid]["category"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("🎯 Meta salva!", reply_markup=menu())

# ================= ANALISE =================

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    cur.execute("SELECT type, amount, category, description, created_at FROM transactions WHERE user_id=?", (uid,))
    rows = cur.fetchall()

    total_inc = sum(r[1] for r in rows if r[0] == "income")
    total_exp = sum(r[1] for r in rows if r[0] == "expense")

    msg = "📊 ANÁLISE FINANCEIRA\n\n"
    msg += f"📈 Ganhos: R$ {total_inc:.2f}\n"
    msg += f"📉 Gastos: R$ {total_exp:.2f}\n"
    msg += f"💰 Saldo: R$ {total_inc-total_exp:.2f}\n\n"

    msg += "🧾 Últimos registros:\n"
    for r in rows[-10:]:
        msg += f"🕒 {r[4]} — R$ {r[1]:.2f} — {r[2]} — {r[3]}\n"

    await update.callback_query.edit_message_text(msg, reply_markup=menu())

# ================= HISTÓRICO =================

async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    cur.execute("""
        SELECT amount, category, description, created_at 
        FROM transactions 
        WHERE user_id=? 
        ORDER BY id DESC LIMIT 20
    """, (uid,))
    
    rows = cur.fetchall()

    if not rows:
        await update.callback_query.edit_message_text("📭 Sem registros", reply_markup=menu())
        return

    msg = "📋 HISTÓRICO\n\n"
    for r in rows:
        msg += f"🕒 {r[3]} — R$ {r[0]:.2f} — {r[1]} — {r[2]}\n"

    await update.callback_query.edit_message_text(msg, reply_markup=menu())

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(start_gasto, pattern="^gasto$"))
    app.add_handler(CallbackQueryHandler(start_ganho, pattern="^ganho$"))

    app.add_handler(CallbackQueryHandler(new_cat, pattern="^newcat$"))
    app.add_handler(CallbackQueryHandler(save_cat_type, pattern="^type_"))

    app.add_handler(CallbackQueryHandler(renda_start, pattern="^addrenda$"))
    app.add_handler(CallbackQueryHandler(fixed_start, pattern="^fixo$"))
    app.add_handler(CallbackQueryHandler(meta_start, pattern="^meta$"))

    app.add_handler(CallbackQueryHandler(analise, pattern="^analise$"))
    app.add_handler(CallbackQueryHandler(historico, pattern="^historico$"))

    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_desc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_cat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, renda_name))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, renda_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fixed_name))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fixed_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, meta_category))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, meta_value))

    print("🤖 BOT FINANCEIRO PREMIUM ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
