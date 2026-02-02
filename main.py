import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    raise RuntimeError("TOKEN NÃO DEFINIDO — Configure TELEGRAM_TOKEN nas Environment Variables")

# ===== BANCO DE DADOS =====
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    type TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    category TEXT,
    type TEXT,
    date TEXT
)
""")

conn.commit()

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Registrar Ganho", callback_data="add_income")],
        [InlineKeyboardButton("➖ Registrar Gasto", callback_data="add_expense")],
        [InlineKeyboardButton("📂 Gerenciar Categorias", callback_data="manage_categories")],
        [InlineKeyboardButton("📊 Análise Completa", callback_data="analysis")]
    ]
    await update.message.reply_text("💰 *Bot Financeiro Avançado*\nEscolha uma opção:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ===== MENU CALLBACK =====
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "add_income":
        context.user_data["type"] = "income"
        await query.message.reply_text("Digite o valor do GANHO:")

    elif query.data == "add_expense":
        context.user_data["type"] = "expense"
        await query.message.reply_text("Digite o valor do GASTO:")

    elif query.data == "manage_categories":
        await show_categories_menu(query)

    elif query.data == "analysis":
        await generate_analysis(query)

    elif query.data.startswith("cat_"):
        category = query.data.replace("cat_", "")
        await save_transaction(query, context, category)

    elif query.data.startswith("delcat_"):
        cat = query.data.replace("delcat_", "")
        cursor.execute("DELETE FROM categories WHERE name=?", (cat,))
        conn.commit()
        await query.message.reply_text(f"🗑 Categoria removida: {cat}")

# ===== ENTRADA DE VALOR =====
async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.replace(",", "."))
        context.user_data["amount"] = value
        await ask_category(update, context)
    except:
        await update.message.reply_text("⚠️ Digite um valor válido!")

# ===== ESCOLHER CATEGORIA =====
async def ask_category(update, context):
    ttype = context.user_data["type"]
    cursor.execute("SELECT name FROM categories WHERE type=?", (ttype,))
    cats = cursor.fetchall()

    if not cats:
        await update.message.reply_text("⚠️ Nenhuma categoria criada. Crie uma primeiro em Categorias.")
        return

    keyboard = [[InlineKeyboardButton(c[0], callback_data=f"cat_{c[0]}")] for c in cats]
    await update.message.reply_text("📂 Escolha uma categoria:", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== SALVAR TRANSAÇÃO =====
async def save_transaction(query, context, category):
    user_id = query.from_user.id
    amount = context.user_data["amount"]
    ttype = context.user_data["type"]
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute(
        "INSERT INTO transactions (user_id, amount, category, type, date) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, ttype, date)
    )
    conn.commit()

    label = "Ganho" if ttype == "income" else "Gasto"
    await query.message.reply_text(f"✅ {label} registrado: R$ {amount:.2f} em {category}")

# ===== CATEGORIAS =====
async def show_categories_menu(query):
    cursor.execute("SELECT name, type FROM categories")
    rows = cursor.fetchall()

    text = "📂 *Categorias*\n\n"
    keyboard = []

    for name, ttype in rows:
        label = "🟢 Ganho" if ttype == "income" else "🔴 Gasto"
        text += f"{label} — {name}\n"
        keyboard.append([InlineKeyboardButton(f"❌ {name}", callback_data=f"delcat_{name}")])

    keyboard.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_category")])

    await query.message.reply_text(text or "Sem categorias", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ===== NOVA CATEGORIA =====
async def new_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cat"] = True
    await update.callback_query.message.reply_text("Digite: NomeDaCategoria | income ou expense")

async def save_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("new_cat"):
        try:
            name, ttype = update.message.text.split("|")
            name = name.strip()
            ttype = ttype.strip()

            if ttype not in ["income", "expense"]:
                raise ValueError()

            cursor.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (name, ttype))
            conn.commit()

            context.user_data["new_cat"] = False
            await update.message.reply_text(f"✅ Categoria criada: {name}")
        except:
            await update.message.reply_text("⚠️ Formato errado! Ex: Mercado | expense")

# ===== RELATÓRIO =====
async def generate_analysis(query):
    user_id = query.from_user.id

    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='income'", (user_id,))
    income = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='expense'", (user_id,))
    expense = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT category, SUM(amount) 
        FROM transactions 
        WHERE user_id=? 
        GROUP BY category
    """, (user_id,))
    categories = cursor.fetchall()

    text = f"📊 *ANÁLISE FINANCEIRA COMPLETA*\n\n"
    text += f"🟢 Total Ganhos: R$ {income:.2f}\n"
    text += f"🔴 Total Gastos: R$ {expense:.2f}\n"
    text += f"💰 Saldo: R$ {income - expense:.2f}\n\n"
    text += "📂 *Por Categoria:*\n"

    for cat, total in categories:
        text += f"• {cat}: R$ {total:.2f}\n"

    await query.message.reply_text(text, parse_mode="Markdown")

# ===== MAIN =====
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_category))

    print("🤖 Bot rodando...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
