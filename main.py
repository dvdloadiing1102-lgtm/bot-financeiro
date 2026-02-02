import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN na Render")

# Banco
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    category TEXT,
    amount REAL,
    date TEXT
)
""")
conn.commit()

CATEGORIES = ["Alimentação", "Transporte", "Lazer", "Aluguel", "Salário", "Outros"]
user_state = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Gasto", callback_data="expense")],
        [InlineKeyboardButton("💰 Ganho", callback_data="income")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report")]
    ]
    await update.message.reply_text(
        "📌 *Bot Financeiro*\nEscolha:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data in ["expense", "income"]:
        user_state[user_id] = {"type": query.data}
        buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in CATEGORIES]
        await query.edit_message_text("📂 Categoria:", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "report":
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? GROUP BY type", (user_id,))
        data = cursor.fetchall()

        income = sum(v for t, v in data if t == "income")
        expense = sum(v for t, v in data if t == "expense")

        msg = (
            f"📊 *Relatório*\n\n"
            f"💰 Ganhos: R$ {income:.2f}\n"
            f"💸 Gastos: R$ {expense:.2f}\n"
            f"📉 Saldo: R$ {income-expense:.2f}"
        )

        await query.edit_message_text(msg, parse_mode="Markdown")

async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    category = query.data.replace("cat_", "")
    user_state[user_id]["category"] = category

    await query.edit_message_text("💵 Digite o valor:")

async def save_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_state:
        return

    try:
        value = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Digite um número válido.")
        return

    data = user_state[user_id]

    cursor.execute(
        "INSERT INTO transactions (user_id, type, category, amount, date) VALUES (?, ?, ?, ?, ?)",
        (user_id, data["type"], data["category"], value, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()

    del user_state[user_id]

    await update.message.reply_text("✅ Salvo com sucesso!")

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu, pattern="expense|income|report"))
    app.add_handler(CallbackQueryHandler(select_category, pattern="cat_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_value))

    print("🤖 Bot online...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
