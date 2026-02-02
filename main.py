import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    raise RuntimeError("Defina TELEGRAM_TOKEN nas variáveis de ambiente da Render")

# Banco SQLite
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    category TEXT,
    amount REAL,
    description TEXT,
    date TEXT
)
""")
conn.commit()

# Categorias padrão
CATEGORIES = ["Alimentação", "Transporte", "Lazer", "Aluguel", "Salário", "Outros"]

# Estados temporários
user_states = {}

# Menu principal
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Registrar Gasto", callback_data="add_expense")],
        [InlineKeyboardButton("💰 Registrar Ganho", callback_data="add_income")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report")]
    ]
    await update.message.reply_text(
        "📌 *Menu Financeiro*\nEscolha uma opção:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# Botões
async def menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data in ["add_expense", "add_income"]:
        user_states[user_id] = {"type": query.data}
        buttons = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in CATEGORIES]
        await query.edit_message_text("📂 Escolha uma categoria:", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "report":
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? GROUP BY type", (user_id,))
        rows = cursor.fetchall()

        income = sum(r[1] for r in rows if r[0] == "add_income")
        expense = sum(r[1] for r in rows if r[0] == "add_expense")

        text = f"📊 *Relatório*\n\n💰 Ganhos: R$ {income:.2f}\n💸 Gastos: R$ {expense:.2f}\n📉 Saldo: R$ {income-expense:.2f}"

        await query.edit_message_text(text, parse_mode="Markdown")

# Categoria escolhida
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    category = query.data.replace("cat_", "")

    user_states[user_id]["category"] = category

    await query.edit_message_text("💵 Envie o valor (ex: 50.90)")

# Valor digitado
async def value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_states:
        return

    try:
        value = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Envie um número.")
        return

    state = user_states[user_id]

    cursor.execute("""
        INSERT INTO transactions (user_id, type, category, amount, description, date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        state["type"],
        state["category"],
        value,
        "Registro manual",
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    del user_states[user_id]

    await update.message.reply_text("✅ Registro salvo!")

# Inicialização
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_click, pattern="add_|report"))
    app.add_handler(CallbackQueryHandler(category_selected, pattern="cat_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, value_received))

    print("🤖 Bot rodando...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
