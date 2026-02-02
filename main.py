import os
import sqlite3
import threading
import time
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN na Render")

# ================= ANTI-SLEEP INVISÍVEL =================

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot vivo e acordado")

def run_keep_alive():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), KeepAliveHandler).serve_forever()

def self_ping():
    url = os.getenv("RENDER_EXTERNAL_URL")
    while True:
        try:
            if url:
                requests.get(url)
                print("PING OK — bot acordado")
        except:
            pass
        time.sleep(240)

threading.Thread(target=run_keep_alive, daemon=True).start()
threading.Thread(target=self_ping, daemon=True).start()

# ================= DATABASE =================

conn = sqlite3.connect("finance.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY
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
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    limit_value REAL
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

conn.commit()

# ================= MEMORY =================

user_state = {}

# ================= HELPERS =================

def init_user(uid):
    cur.execute("INSERT OR IGNORE INTO users VALUES (?)", (uid,))
    conn.commit()

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Gastar", callback_data="gasto"),
         InlineKeyboardButton("💰 Ganhar", callback_data="ganho")],

        [InlineKeyboardButton("🏷️ Categorias", callback_data="newcat"),
         InlineKeyboardButton("📦 Custos Fixos", callback_data="fixo")],

        [InlineKeyboardButton("🎯 Metas", callback_data="meta"),
         InlineKeyboardButton("📊 Relatórios", callback_data="analise")],

        [InlineKeyboardButton("📋 Histórico", callback_data="historico"),
         InlineKeyboardButton("🗑️ Lixeira", callback_data="lixeira")]
    ])

def get_categories(uid, t):
    cur.execute("SELECT name FROM categories WHERE user_id=? AND type=?", (uid, t))
    return [x[0] for x in cur.fetchall()]

def add_transaction(uid, t, amount, cat, desc):
    cur.execute("""
        INSERT INTO transactions (user_id, type, amount, category, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (uid, t, amount, cat, desc, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_user(update.effective_user.id)
    await update.message.reply_text("💳 Banco do David™\nModo Premium ativado.", reply_markup=menu())

# ================= GASTO / GANHO =================

async def start_gasto(update, context):
    user_state[update.callback_query.from_user.id] = {"type": "expense"}
    await update.callback_query.edit_message_text("💸 Valor do gasto:")

async def start_ganho(update, context):
    user_state[update.callback_query.from_user.id] = {"type": "income"}
    await update.callback_query.edit_message_text("💰 Valor do ganho:")

async def receive_value(update, context):
    uid = update.message.from_user.id
    if uid not in user_state:
        return

    try:
        val = float(update.message.text.replace(",", "."))
        user_state[uid]["value"] = val
    except:
        await update.message.reply_text("❌ Digita número direito, milionário.")
        return

    t = user_state[uid]["type"]
    cats = get_categories(uid, t)

    if not cats:
        await update.message.reply_text("⚠️ Crie categoria antes.")
        return

    buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
    await update.message.reply_text("📂 Escolha categoria:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_category(update, context):
    uid = update.callback_query.from_user.id
    user_state[uid]["category"] = update.callback_query.data.replace("cat_", "")
    await update.callback_query.edit_message_text("📝 Descrição do gasto/ganho:")

async def receive_desc(update, context):
    uid = update.message.from_user.id
    if uid not in user_state:
        return

    d = user_state[uid]
    add_transaction(uid, d["type"], d["value"], d["category"], update.message.text)

    if d["type"] == "expense" and d["value"] > 300:
        joke = "⚠️ Gastou pesado… carteira chorou."
    else:
        joke = "✅ Registro salvo."

    del user_state[uid]
    await update.message.reply_text(joke, reply_markup=menu())

# ================= CATEGORIAS =================

async def new_cat(update, context):
    user_state[update.callback_query.from_user.id] = {"mode": "newcat"}
    await update.callback_query.edit_message_text("Nome da categoria:")

async def save_cat(update, context):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "newcat":
        return

    user_state[uid]["name"] = update.message.text
    await update.message.reply_text(
        "Tipo:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Gasto", callback_data="type_expense")],
            [InlineKeyboardButton("💰 Ganho", callback_data="type_income")]
        ])
    )

async def save_cat_type(update, context):
    uid = update.callback_query.from_user.id
    t = "expense" if "expense" in update.callback_query.data else "income"

    cur.execute("INSERT INTO categories (user_id, name, type) VALUES (?, ?, ?)",
                (uid, user_state[uid]["name"], t))
    conn.commit()

    del user_state[uid]
    await update.callback_query.edit_message_text("✅ Categoria criada.", reply_markup=menu())

# ================= METAS =================

async def meta_start(update, context):
    user_state[update.callback_query.from_user.id] = {"mode": "meta"}
    await update.callback_query.edit_message_text("Categoria da meta:")

async def meta_category(update, context):
    uid = update.message.from_user.id
    user_state[uid]["category"] = update.message.text
    await update.message.reply_text("Valor limite:")

async def meta_value(update, context):
    uid = update.message.from_user.id
    val = float(update.message.text.replace(",", "."))

    cur.execute("INSERT INTO goals VALUES (NULL, ?, ?, ?)", (uid, user_state[uid]["category"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("🎯 Meta salva.", reply_markup=menu())

# ================= ANALISE =================

async def analise(update, context):
    uid = update.callback_query.from_user.id

    cur.execute("SELECT type, amount, category, description, created_at FROM transactions WHERE user_id=?", (uid,))
    rows = cur.fetchall()

    total_g = sum(x[1] for x in rows if x[0] == "income")
    total_d = sum(x[1] for x in rows if x[0] == "expense")

    msg = f"""
📊 RELATÓRIO PREMIUM

💰 Ganhos: R$ {total_g:.2f}
💸 Gastos: R$ {total_d:.2f}
📉 Saldo: R$ {total_g-total_d:.2f}

Últimos gastos:
"""

    for r in rows[-10:]:
        msg += f"🕒 {r[4]} — R$ {r[1]:.2f} — {r[2]} — {r[3]}\n"

    if total_d > total_g:
        msg += "\n⚠️ Você gastou mais que ganhou… modo econômico recomendado."

    await update.callback_query.edit_message_text(msg, reply_markup=menu())

# ================= LIXEIRA =================

async def lixeira(update, context):
    uid = update.callback_query.from_user.id
    cur.execute("DELETE FROM transactions WHERE user_id=?", (uid,))
    conn.commit()
    await update.callback_query.edit_message_text("🗑️ Histórico limpo.", reply_markup=menu())

# ================= HISTÓRICO =================

async def historico(update, context):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT amount, category, description, created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))
    rows = cur.fetchall()

    if not rows:
        await update.callback_query.edit_message_text("📭 Sem registros.", reply_markup=menu())
        return

    msg = "📋 HISTÓRICO\n\n"
    for r in rows:
        msg += f"{r[3]} — R$ {r[0]:.2f} — {r[1]} — {r[2]}\n"

    await update.callback_query.edit_message_text(msg, reply_markup=menu())

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(start_gasto, pattern="^gasto$"))
    app.add_handler(CallbackQueryHandler(start_ganho, pattern="^ganho$"))
    app.add_handler(CallbackQueryHandler(new_cat, pattern="^newcat$"))
    app.add_handler(CallbackQueryHandler(save_cat_type, pattern="^type_"))
    app.add_handler(CallbackQueryHandler(meta_start, pattern="^meta$"))
    app.add_handler(CallbackQueryHandler(analise, pattern="^analise$"))
    app.add_handler(CallbackQueryHandler(historico, pattern="^historico$"))
    app.add_handler(CallbackQueryHandler(lixeira, pattern="^lixeira$"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_desc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_cat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, meta_category))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, meta_value))

    print("🤖 BANCO DO DAVID PREMIUM ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
