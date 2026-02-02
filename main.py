import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN na Render")

# ================= DATABASE =================

conn = sqlite3.connect("finance.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    dark_mode INTEGER DEFAULT 1
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
    cur.execute("INSERT OR IGNORE INTO users (telegram_id, dark_mode) VALUES (?, 1)", (tid,))
    conn.commit()

def get_user_dark_mode(tid):
    cur.execute("SELECT dark_mode FROM users WHERE telegram_id=?", (tid,))
    result = cur.fetchone()
    return result[0] if result else 1

def toggle_dark_mode(tid):
    current = get_user_dark_mode(tid)
    cur.execute("UPDATE users SET dark_mode=? WHERE telegram_id=?", (1 - current, tid))
    conn.commit()
    return 1 - current

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
        [InlineKeyboardButton("📋 Histórico", callback_data="historico")],
        [InlineKeyboardButton("🌙 Modo Anti Sono", callback_data="toggle_dark")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_user(update.effective_user.id)
    await update.message.reply_text("🤖 Bot Financeiro Premium", reply_markup=menu())

# ================= VOLTAR =================

async def voltar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retorna ao menu principal"""
    uid = update.callback_query.from_user.id
    if uid in user_state:
        del user_state[uid]
    await update.callback_query.edit_message_text("🤖 Bot Financeiro Premium", reply_markup=menu())

# ================= TOGGLE DARK MODE =================

async def toggle_dark_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa/desativa modo anti sono (dark mode)"""
    uid = update.callback_query.from_user.id
    new_mode = toggle_dark_mode(uid)
    status = "🌙 Ativado" if new_mode == 1 else "☀️ Desativado"
    await update.callback_query.answer(f"Modo Anti Sono {status}", show_alert=True)
    await update.callback_query.edit_message_text("🤖 Bot Financeiro Premium", reply_markup=menu())

# ================= GASTO / GANHO =================

async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"type": "expense", "step": "value"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("💰 Digite o valor do gasto:", reply_markup=InlineKeyboardMarkup(buttons))

async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"type": "income", "step": "value"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("💰 Digite o valor do ganho:", reply_markup=InlineKeyboardMarkup(buttons))

async def receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "value":
        return

    try:
        val = float(update.message.text.replace(",", "."))
        user_state[uid]["value"] = val
        user_state[uid]["step"] = "category"
    except:
        await update.message.reply_text("❌ Valor inválido. Digite um número válido.")
        return

    ctype = "expense" if user_state[uid]["type"] == "expense" else "income"
    cats = get_categories(uid, ctype)

    if not cats:
        await update.message.reply_text("❗ Cadastre uma categoria primeiro")
        return

    buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
    buttons.append([InlineKeyboardButton("✅ Múltiplas Categorias", callback_data="cat_all")])
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")])
    await update.message.reply_text("📂 Escolha categoria:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cat = update.callback_query.data.replace("cat_", "")
    user_state[uid]["category"] = cat
    user_state[uid]["step"] = "description"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("📝 Digite a descrição:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_category_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opção para cadastrar em múltiplas categorias"""
    uid = update.callback_query.from_user.id
    user_state[uid]["category"] = "Múltiplas Categorias"
    user_state[uid]["step"] = "description"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("📝 Digite a descrição:", reply_markup=InlineKeyboardMarkup(buttons))

async def receive_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "description":
        return

    desc = update.message.text
    data = user_state[uid]

    add_transaction(uid, data["type"], data["value"], data["category"], desc)
    del user_state[uid]

    await update.message.reply_text("✅ Registro salvo com sucesso!", reply_markup=menu())

# ================= ADD CATEGORY =================

async def new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "newcat", "step": "name"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite o nome da categoria:", reply_markup=InlineKeyboardMarkup(buttons))

async def save_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "newcat" or user_state[uid].get("step") != "name":
        return

    name = update.message.text
    user_state[uid]["name"] = name
    user_state[uid]["step"] = "type"

    buttons = [
        [InlineKeyboardButton("📉 Gasto", callback_data="type_expense")],
        [InlineKeyboardButton("📈 Ganho", callback_data="type_income")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]
    ]
    await update.message.reply_text("Escolha o tipo da categoria:", reply_markup=InlineKeyboardMarkup(buttons))

async def save_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    
    if uid not in user_state or user_state[uid].get("mode") != "newcat":
        await update.callback_query.answer("Erro ao processar", show_alert=True)
        return
    
    ctype = "expense" if "expense" in update.callback_query.data else "income"
    name = user_state[uid].get("name")
    
    if not name:
        await update.callback_query.answer("Erro: nome da categoria não encontrado", show_alert=True)
        return

    add_category(uid, name, ctype)
    del user_state[uid]

    await update.callback_query.edit_message_text("✅ Categoria criada com sucesso!", reply_markup=menu())

# ================= RENDA =================

async def renda_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "renda", "step": "name"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite o nome da renda:", reply_markup=InlineKeyboardMarkup(buttons))

async def renda_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "renda" or user_state[uid].get("step") != "name":
        return
    user_state[uid]["name"] = update.message.text
    user_state[uid]["step"] = "value"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.message.reply_text("Digite o valor da renda:", reply_markup=InlineKeyboardMarkup(buttons))

async def renda_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "renda" or user_state[uid].get("step") != "value":
        return
    
    try:
        val = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Digite um número válido.")
        return

    cur.execute("INSERT INTO incomes (user_id, name, value) VALUES (?, ?, ?)",
                (uid, user_state[uid]["name"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("✅ Renda salva com sucesso!", reply_markup=menu())

# ================= CUSTO FIXO =================

async def fixed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "fixo", "step": "name"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite o nome do custo fixo:", reply_markup=InlineKeyboardMarkup(buttons))

async def fixed_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "fixo" or user_state[uid].get("step") != "name":
        return
    user_state[uid]["name"] = update.message.text
    user_state[uid]["step"] = "value"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.message.reply_text("Digite o valor do custo:", reply_markup=InlineKeyboardMarkup(buttons))

async def fixed_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "fixo" or user_state[uid].get("step") != "value":
        return
    
    try:
        val = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Digite um número válido.")
        return

    cur.execute("INSERT INTO fixed_costs (user_id, name, value) VALUES (?, ?, ?)",
                (uid, user_state[uid]["name"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("✅ Custo fixo cadastrado com sucesso!", reply_markup=menu())

# ================= META =================

async def meta_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "meta", "step": "category"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite a categoria da meta:", reply_markup=InlineKeyboardMarkup(buttons))

async def meta_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "meta" or user_state[uid].get("step") != "category":
        return
    user_state[uid]["category"] = update.message.text
    user_state[uid]["step"] = "value"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.message.reply_text("Digite o valor limite da meta:", reply_markup=InlineKeyboardMarkup(buttons))

async def meta_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("mode") != "meta" or user_state[uid].get("step") != "value":
        return
    
    try:
        val = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Digite um número válido.")
        return

    cur.execute("INSERT INTO goals (user_id, category, limit_value) VALUES (?, ?, ?)",
                (uid, user_state[uid]["category"], val))
    conn.commit()

    del user_state[uid]
    await update.message.reply_text("🎯 Meta salva com sucesso!", reply_markup=menu())

# ================= ANALISE =================

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    cur.execute("SELECT type, amount, category, description, created_at FROM transactions WHERE user_id=?", (uid,))
    rows = cur.fetchall()

    total_inc = sum(r[1] for r in rows if r[0] == "income")
    total_exp = sum(r[1] for r in rows if r[0] == "expense")

    msg = "📊 ANÁLISE COMPLETA\n\n"
    msg += f"💰 Ganhos: R$ {total_inc:.2f}\n"
    msg += f"💸 Gastos: R$ {total_exp:.2f}\n"
    msg += f"📉 Saldo: R$ {total_inc-total_exp:.2f}\n\n"

    msg += "🔥 Últimos gastos:\n"
    for r in rows[-10:]:
        msg += f"🕒 {r[4]} — R$ {r[1]:.2f} — {r[2]} — {r[3]}\n"

    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

# ================= HISTÓRICO =================

async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT amount, category, description, created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))
    rows = cur.fetchall()

    if not rows:
        buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
        await update.callback_query.edit_message_text("📭 Sem registros", reply_markup=InlineKeyboardMarkup(buttons))
        return

    msg = "📋 HISTÓRICO\n\n"
    for r in rows:
        msg += f"🕒 {r[3]} — R$ {r[0]:.2f} — {r[1]} — {r[2]}\n"

    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Handlers para voltar
    app.add_handler(CallbackQueryHandler(voltar, pattern="^voltar$"))
    app.add_handler(CallbackQueryHandler(toggle_dark_mode_handler, pattern="^toggle_dark$"))

    # Handlers para gasto/ganho
    app.add_handler(CallbackQueryHandler(start_gasto, pattern="^gasto$"))
    app.add_handler(CallbackQueryHandler(start_ganho, pattern="^ganho$"))

    # Handlers para categoria
    app.add_handler(CallbackQueryHandler(new_cat, pattern="^newcat$"))
    app.add_handler(CallbackQueryHandler(save_cat_type, pattern="^type_"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(choose_category_all, pattern="^cat_all$"))

    # Handlers para renda
    app.add_handler(CallbackQueryHandler(renda_start, pattern="^addrenda$"))

    # Handlers para custo fixo
    app.add_handler(CallbackQueryHandler(fixed_start, pattern="^fixo$"))

    # Handlers para meta
    app.add_handler(CallbackQueryHandler(meta_start, pattern="^meta$"))

    # Handlers para análise e histórico
    app.add_handler(CallbackQueryHandler(analise, pattern="^analise$"))
    app.add_handler(CallbackQueryHandler(historico, pattern="^historico$"))

    # Handlers para mensagens de texto (com verificação de step)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_desc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_cat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, renda_name))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, renda_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fixed_name))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fixed_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, meta_category))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, meta_value))

    print("🤖 FINANCEIRO PREMIUM ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
