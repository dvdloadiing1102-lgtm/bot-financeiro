import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = "SEU_TOKEN_AQUI"

# ================== BANCO ==================
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS categories (
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT,
type TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
id INTEGER PRIMARY KEY AUTOINCREMENT,
type TEXT,
category TEXT,
value REAL,
description TEXT,
date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS fixed_costs (
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT,
value REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS goals (
id INTEGER PRIMARY KEY AUTOINCREMENT,
category TEXT,
limit_value REAL
)
""")

conn.commit()

user_state = {}

# ================== MENU ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💸 Novo Gasto", callback_data="new_expense")],
        [InlineKeyboardButton("💰 Novo Ganho", callback_data="new_income")],
        [InlineKeyboardButton("📂 Categorias", callback_data="categories")],
        [InlineKeyboardButton("📊 Análise Completa", callback_data="analysis")],
        [InlineKeyboardButton("📌 Custos Fixos", callback_data="fixed")],
        [InlineKeyboardButton("🎯 Metas & Alertas", callback_data="goals")]
    ]
    await update.message.reply_text("🏦 BOT FINANCEIRO — MENU", reply_markup=InlineKeyboardMarkup(keyboard))

# ================== CALLBACK ==================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "new_expense":
        user_state[query.from_user.id] = {"type": "expense"}
        await query.message.reply_text("Digite o valor do gasto:")

    elif data == "new_income":
        user_state[query.from_user.id] = {"type": "income"}
        await query.message.reply_text("Digite o valor do ganho:")

    elif data == "categories":
        await query.message.reply_text("Digite: categoria gasto OU categoria ganho")

    elif data == "analysis":
        await show_analysis(query)

    elif data == "fixed":
        await query.message.reply_text("Digite: custo Nome Valor")

    elif data == "goals":
        await query.message.reply_text("Digite: meta Categoria ValorLimite")

# ================== TEXTO ==================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    # Criar categoria
    if text.lower().startswith("categoria"):
        _, tipo = text.split()
        await update.message.reply_text("Digite o nome da categoria:")
        user_state[user_id] = {"action": "add_category", "type": tipo}
        return

    # Criar custo fixo
    if text.lower().startswith("custo"):
        _, name, value = text.split(maxsplit=2)
        cursor.execute("INSERT INTO fixed_costs VALUES(NULL, ?, ?)", (name, float(value)))
        conn.commit()
        await update.message.reply_text("✅ Custo fixo adicionado!")
        return

    # Criar meta
    if text.lower().startswith("meta"):
        _, cat, limit_value = text.split()
        cursor.execute("INSERT INTO goals VALUES(NULL, ?, ?)", (cat, float(limit_value)))
        conn.commit()
        await update.message.reply_text("🎯 Meta criada!")
        return

    # Categoria salva
    if user_id in user_state and user_state[user_id].get("action") == "add_category":
        tipo = user_state[user_id]["type"]
        cursor.execute("INSERT INTO categories VALUES(NULL, ?, ?)", (text, tipo))
        conn.commit()
        await update.message.reply_text(f"✅ Categoria {text} criada ({tipo})")
        user_state.pop(user_id)
        return

    # Novo gasto ou ganho
    if user_id in user_state and "type" in user_state[user_id] and "value" not in user_state[user_id]:
        user_state[user_id]["value"] = float(text)
        cats = cursor.execute("SELECT name FROM categories WHERE type=?", (user_state[user_id]["type"],)).fetchall()
        if not cats:
            await update.message.reply_text("❌ Crie categorias primeiro.")
            return
        buttons = [[InlineKeyboardButton(c[0], callback_data=f"cat_{c[0]}")] for c in cats]
        await update.message.reply_text("Escolha a categoria:", reply_markup=InlineKeyboardMarkup(buttons))
        return

# ================== SELECIONAR CATEGORIA ==================
async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    category = query.data.replace("cat_", "")

    data = user_state[user_id]
    value = data["value"]
    trans_type = data["type"]

    user_state[user_id]["category"] = category
    await query.message.reply_text("Digite a descrição:")
    user_state[user_id]["step"] = "desc"

# ================== SALVAR TRANSAÇÃO ==================
async def save_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_state or user_state[user_id].get("step") != "desc":
        return

    desc = update.message.text
    data = user_state[user_id]

    cursor.execute("""
    INSERT INTO transactions VALUES(NULL, ?, ?, ?, ?, ?)
    """, (
        data["type"],
        data["category"],
        data["value"],
        desc,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    await update.message.reply_text("✅ Transação registrada!")

    await check_goals(update, data["category"])

    user_state.pop(user_id)

# ================== METAS ==================
async def check_goals(update, category):
    goal = cursor.execute("SELECT limit_value FROM goals WHERE category=?", (category,)).fetchone()
    if goal:
        total = cursor.execute("SELECT SUM(value) FROM transactions WHERE category=? AND type='expense'", (category,)).fetchone()[0] or 0
        limit_value = goal[0]

        if total >= limit_value * 0.8 and total < limit_value:
            await update.message.reply_text(f"⚠️ Você gastou 80% do limite em {category}. Vai comer ovo 🍳")
        elif total >= limit_value:
            await update.message.reply_text(f"🚨 LIMITE ESTOURADO EM {category}!")

# ================== ANÁLISE ==================
async def show_analysis(query):
    expenses = cursor.execute("SELECT category, SUM(value) FROM transactions WHERE type='expense' GROUP BY category").fetchall()
    incomes = cursor.execute("SELECT SUM(value) FROM transactions WHERE type='income'").fetchone()[0] or 0

    text = "📊 ANÁLISE COMPLETA\n\n💸 Gastos por categoria:\n"
    total_exp = 0

    for cat, val in expenses:
        total_exp += val
        text += f"• {cat}: R$ {val:.2f}\n"

    text += f"\n💰 Total Ganhos: R$ {incomes:.2f}"
    text += f"\n💸 Total Gastos: R$ {total_exp:.2f}"
    text += f"\n📈 Saldo: R$ {incomes - total_exp:.2f}"

    await query.message.reply_text(text)

# ================== MAIN ==================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(CallbackQueryHandler(select_category, pattern="^cat_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_description))

    print("🤖 BOT FINANCEIRO ONLINE")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
