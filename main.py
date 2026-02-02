import sqlite3
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from aiohttp import web

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS incomes (
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT,
value REAL,
date TEXT
)
""")

conn.commit()

user_state = {}

# ================== ANTI SLEEP ==================
async def handle(request):
    return web.Response(text="Bot ativo")

async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

# ================== MENU ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💸 Novo Gasto", callback_data="new_expense")],
        [InlineKeyboardButton("💰 Novo Ganho", callback_data="new_income")],
        [InlineKeyboardButton("📂 Criar Categoria", callback_data="categories")],
        [InlineKeyboardButton("💼 Custos Fixos", callback_data="fixed_costs")],
        [InlineKeyboardButton("🎯 Criar Meta", callback_data="goals")],
        [InlineKeyboardButton("📊 Análise Completa", callback_data="analysis")]
    ]
    await update.message.reply_text("🏦 BOT FINANCEIRO MASTER", reply_markup=InlineKeyboardMarkup(keyboard))

# ================== BOTÕES ==================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "new_expense":
        user_state[uid] = {"type": "expense"}
        await query.message.reply_text("Digite o valor do gasto:")

    elif query.data == "new_income":
        user_state[uid] = {"type": "income"}
        await query.message.reply_text("Digite o valor do ganho:")

    elif query.data == "categories":
        user_state[uid] = {"action": "add_category"}
        await query.message.reply_text("Digite: Nome da categoria | expense ou income")

    elif query.data == "fixed_costs":
        user_state[uid] = {"action": "add_fixed"}
        await query.message.reply_text("Digite: Nome do custo fixo | valor")

    elif query.data == "goals":
        user_state[uid] = {"action": "add_goal"}
        await query.message.reply_text("Digite: Categoria | Limite")

    elif query.data == "analysis":
        await show_analysis(query)

# ================== TEXTO ==================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # Nova categoria
    if uid in user_state and user_state[uid].get("action") == "add_category":
        try:
            name, tipo = text.split("|")
            cursor.execute("INSERT INTO categories VALUES(NULL, ?, ?)", (name.strip(), tipo.strip()))
            conn.commit()
            await update.message.reply_text("✅ Categoria criada!")
        except:
            await update.message.reply_text("❌ Formato errado. Exemplo: Alimentação | expense")
        user_state.pop(uid)
        return

    # Novo custo fixo
    if uid in user_state and user_state[uid].get("action") == "add_fixed":
        try:
            name, value = text.split("|")
            cursor.execute("INSERT INTO fixed_costs VALUES(NULL, ?, ?)", (name.strip(), float(value)))
            conn.commit()
            await update.message.reply_text("✅ Custo fixo cadastrado!")
        except:
            await update.message.reply_text("❌ Exemplo: Netflix | 55")
        user_state.pop(uid)
        return

    # Nova meta
    if uid in user_state and user_state[uid].get("action") == "add_goal":
        try:
            cat, limit_value = text.split("|")
            cursor.execute("INSERT INTO goals VALUES(NULL, ?, ?)", (cat.strip(), float(limit_value)))
            conn.commit()
            await update.message.reply_text("🎯 Meta criada!")
        except:
            await update.message.reply_text("❌ Exemplo: iFood | 300")
        user_state.pop(uid)
        return

    # Valor gasto/ganho
    if uid in user_state and "type" in user_state[uid] and "value" not in user_state[uid]:
        try:
            user_state[uid]["value"] = float(text)
            cats = cursor.execute("SELECT name FROM categories WHERE type=?", (user_state[uid]["type"],)).fetchall()

            if not cats:
                await update.message.reply_text("❌ Crie categorias primeiro.")
                user_state.pop(uid)
                return

            buttons = [[InlineKeyboardButton(c[0], callback_data=f"cat_{c[0]}")] for c in cats]
            await update.message.reply_text("Escolha a categoria:", reply_markup=InlineKeyboardMarkup(buttons))
            return
        except:
            await update.message.reply_text("❌ Digite um número válido.")
            return

# ================== ESCOLHER CATEGORIA ==================
async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    category = query.data.replace("cat_", "")
    user_state[uid]["category"] = category
    user_state[uid]["step"] = "desc"

    await query.message.reply_text("Digite a descrição:")

# ================== SALVAR ==================
async def save_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state or user_state[uid].get("step") != "desc":
        return

    desc = update.message.text
    data = user_state[uid]

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

    await update.message.reply_text("✅ Transação salva!")

    await check_goals(update, data["category"])

    user_state.pop(uid)

# ================== ALERTA DE META ==================
async def check_goals(update, category):
    goal = cursor.execute("SELECT limit_value FROM goals WHERE category=?", (category,)).fetchone()
    if not goal:
        return

    total = cursor.execute("""
        SELECT SUM(value) FROM transactions 
        WHERE type='expense' AND category=?
    """, (category,)).fetchone()[0] or 0

    limit_value = goal[0]
    percent = (total / limit_value) * 100

    if percent >= 80:
        await update.message.reply_text(
            f"⚠️ ALERTA: Você já gastou {percent:.1f}% da meta em {category}!\n"
            "Vai ter que comer ovo o resto do mês 🥚😂"
        )

# ================== ANÁLISE COMPLETA ==================
async def show_analysis(query):
    expenses = cursor.execute("""
        SELECT category, SUM(value) FROM transactions 
        WHERE type='expense' GROUP BY category
    """).fetchall()

    incomes = cursor.execute("""
        SELECT SUM(value) FROM transactions WHERE type='income'
    """).fetchone()[0] or 0

    history = cursor.execute("""
        SELECT value, category, description, date 
        FROM transactions 
        ORDER BY date DESC LIMIT 10
    """).fetchall()

    total_exp = sum(v for _, v in expenses)

    text = "📊 ANÁLISE COMPLETA\n\n"

    text += "💸 GASTOS POR CATEGORIA:\n"
    for cat, val in expenses:
        text += f"• {cat}: R$ {val:.2f}\n"

    text += f"\n💰 GANHOS TOTAIS: R$ {incomes:.2f}"
    text += f"\n💸 GASTOS TOTAIS: R$ {total_exp:.2f}"
    text += f"\n📈 SALDO: R$ {incomes - total_exp:.2f}\n"

    text += "\n🕒 ÚLTIMAS TRANSAÇÕES:\n"
    for v, c, d, dt in history:
        text += f"• R$ {v:.2f} | {c} | {d} | {dt}\n"

    if total_exp > incomes:
        text += "\n⚠️ Você está gastando mais do que ganha!"

    await query.message.reply_text(text)

# ================== MAIN ==================
async def main():
    await start_web()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(CallbackQueryHandler(select_category, pattern="^cat_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_description))

    print("🤖 BOT FINANCEIRO MASTER ONLINE — UPGRADE SEGURO")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
