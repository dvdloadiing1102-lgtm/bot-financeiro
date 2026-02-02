import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

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

cur.execute("""CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER UNIQUE)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS categories (
    user_id INTEGER,
    name TEXT,
    type TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
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
    user_id INTEGER,
    name TEXT,
    value REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS fixed_costs (
    user_id INTEGER,
    name TEXT,
    value REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS goals (
    user_id INTEGER,
    category TEXT,
    limit_value REAL
)
""")

conn.commit()

# ================= MEMORY =================
user_state = {}

# ================= HELPERS =================

def init_user(uid):
    cur.execute("INSERT OR IGNORE INTO users VALUES (?)", (uid,))
    conn.commit()

def get_categories(uid, ctype):
    cur.execute("SELECT name FROM categories WHERE user_id=? AND type=?", (uid, ctype))
    return [x[0] for x in cur.fetchall()]

def add_category(uid, name, ctype):
    cur.execute("INSERT INTO categories VALUES (?, ?, ?)", (uid, name, ctype))
    conn.commit()

def add_transaction(uid, t, amount, cat, desc):
    cur.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
        (uid, t, amount, cat, desc, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
        [InlineKeyboardButton("📊 Análise", callback_data="analise"),
         InlineKeyboardButton("📋 Histórico", callback_data="historico")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_user(update.effective_user.id)
    await update.message.reply_text("🤖 Controle Financeiro Premium", reply_markup=menu())

# ================= GASTO / GANHO =================

async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "value", "type": "expense"}
    await update.callback_query.edit_message_text("💰 Digite o valor do gasto:")

async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "value", "type": "income"}
    await update.callback_query.edit_message_text("💰 Digite o valor do ganho:")

# ================= CATEGORIA =================

async def new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "newcat"}
    await update.callback_query.edit_message_text("🏷️ Nome da categoria:")

async def save_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    ctype = "expense" if update.callback_query.data == "type_expense" else "income"
    name = user_state[uid]["name"]

    add_category(uid, name, ctype)
    del user_state[uid]

    await update.callback_query.edit_message_text("✅ Categoria criada!", reply_markup=menu())

# ================= RENDAS =================

async def renda_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "renda_name"}
    await update.callback_query.edit_message_text("💼 Nome da renda:")

# ================= CUSTO FIXO =================

async def fixed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "fixo_name"}
    await update.callback_query.edit_message_text("📦 Nome do custo fixo:")

# ================= META =================

async def meta_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.callback_query.from_user.id] = {"mode": "meta_cat"}
    await update.callback_query.edit_message_text("🎯 Nome da categoria da meta:")

# ================= MESSAGE ROUTER =================

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()

    if uid not in user_state:
        return

    mode = user_state[uid]["mode"]

    # VALOR TRANSAÇÃO
    if mode == "value":
        try:
            val = float(text.replace(",", "."))
            user_state[uid]["value"] = val
            user_state[uid]["mode"] = "choose_cat"
        except:
            await update.message.reply_text("❌ Valor inválido")
            return

        cats = get_categories(uid, user_state[uid]["type"])
        if not cats:
            await update.message.reply_text("⚠️ Cadastre uma categoria primeiro")
            del user_state[uid]
            return

        buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
        await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(buttons))

    # NOVA CATEGORIA
    elif mode == "newcat":
        user_state[uid]["name"] = text
        buttons = [
            [InlineKeyboardButton("📉 Gasto", callback_data="type_expense")],
            [InlineKeyboardButton("📈 Ganho", callback_data="type_income")]
        ]
        await update.message.reply_text("Tipo da categoria:", reply_markup=InlineKeyboardMarkup(buttons))

    # RENDA
    elif mode == "renda_name":
        user_state[uid]["name"] = text
        user_state[uid]["mode"] = "renda_value"
        await update.message.reply_text("💰 Valor da renda:")

    elif mode == "renda_value":
        val = float(text.replace(",", "."))
        cur.execute("INSERT INTO incomes VALUES (?, ?, ?)", (uid, user_state[uid]["name"], val))
        conn.commit()
        del user_state[uid]
        await update.message.reply_text("✅ Renda salva!", reply_markup=menu())

    # FIXO
    elif mode == "fixo_name":
        user_state[uid]["name"] = text
        user_state[uid]["mode"] = "fixo_value"
        await update.message.reply_text("💰 Valor do custo:")

    elif mode == "fixo_value":
        val = float(text.replace(",", "."))
        cur.execute("INSERT INTO fixed_costs VALUES (?, ?, ?)", (uid, user_state[uid]["name"], val))
        conn.commit()
        del user_state[uid]
        await update.message.reply_text("✅ Custo salvo!", reply_markup=menu())

    # META
    elif mode == "meta_cat":
        user_state[uid]["category"] = text
        user_state[uid]["mode"] = "meta_value"
        await update.message.reply_text("💰 Valor limite:")

    elif mode == "meta_value":
        val = float(text.replace(",", "."))
        cur.execute("INSERT INTO goals VALUES (?, ?, ?)", (uid, user_state[uid]["category"], val))
        conn.commit()
        del user_state[uid]
        await update.message.reply_text("🎯 Meta salva!", reply_markup=menu())

# ================= CALLBACKS =================

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid]["category"] = update.callback_query.data.replace("cat_", "")
    user_state[uid]["mode"] = "desc"
    await update.callback_query.edit_message_text("📝 Descrição:")

async def receive_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid]["mode"] != "desc":
        return

    data = user_state[uid]
    add_transaction(uid, data["type"], data["value"], data["category"], update.message.text)

    del user_state[uid]
    await update.message.reply_text("✅ Registro salvo!", reply_markup=menu())

# ================= ANALISE =================

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT type, amount FROM transactions WHERE user_id=?", (uid,))
    rows = cur.fetchall()

    inc = sum(x[1] for x in rows if x[0] == "income")
    exp = sum(x[1] for x in rows if x[0] == "expense")

    await update.callback_query.edit_message_text(
        f"📊 RESUMO\n\n📈 Ganhos: R$ {inc:.2f}\n📉 Gastos: R$ {exp:.2f}\n💰 Saldo: R$ {inc-exp:.2f}",
        reply_markup=menu()
    )

# ================= HISTÓRICO =================

async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT amount, category, description, created_at FROM transactions WHERE user_id=? ORDER BY rowid DESC LIMIT 15", (uid,))
    rows = cur.fetchall()

    if not rows:
        await update.callback_query.edit_message_text("📭 Sem registros", reply_markup=menu())
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

    app.add_handler(CallbackQueryHandler(renda_start, pattern="^addrenda$"))
    app.add_handler(CallbackQueryHandler(fixed_start, pattern="^fixo$"))
    app.add_handler(CallbackQueryHandler(meta_start, pattern="^meta$"))

    app.add_handler(CallbackQueryHandler(analise, pattern="^analise$"))
    app.add_handler(CallbackQueryHandler(historico, pattern="^historico$"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_desc))

    print("🤖 BOT FINANCEIRO ESTÁVEL ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
