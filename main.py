import os
import json
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN") or "COLOQUE_SEU_TOKEN"

DB_FILE = "db.json"

logging.basicConfig(level=logging.INFO)

# ================= DB =================
def load_db():
    if not os.path.exists(DB_FILE):
        return {
            "transactions": [],
            "categories": {"gasto": [], "ganho": [], "fixo": []},
            "goals": [],
            "fixed_costs": []
        }
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

db = load_db()

# ================= UTIL =================
def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💰 Ganho", callback_data="add_income")],
        [InlineKeyboardButton("💸 Gasto", callback_data="add_expense")],
        [InlineKeyboardButton("📂 Categorias", callback_data="categories")],
        [InlineKeyboardButton("📌 Custos Fixos", callback_data="fixed")],
        [InlineKeyboardButton("🎯 Metas", callback_data="goals")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report")],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data="trash")]
    ]
    await update.message.reply_text(
        "🤖 **Modo Banco ATIVADO**\nZoação moderada ON 😈",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ================= ADD TRANSACTIONS =================
async def add_income(update, context):
    context.user_data["mode"] = "ganho"
    await update.callback_query.message.reply_text("Digite o valor do GANHO:")

async def add_expense(update, context):
    context.user_data["mode"] = "gasto"
    await update.callback_query.message.reply_text("Digite o valor do GASTO:")

async def handle_value(update, context):
    try:
        value = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return

    mode = context.user_data.get("mode")
    context.user_data["value"] = value

    cats = db["categories"][mode]
    if not cats:
        await update.message.reply_text("❌ Nenhuma categoria cadastrada.")
        return

    keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
    await update.message.reply_text("Escolha a categoria:", reply_markup=InlineKeyboardMarkup(keyboard))

async def set_category(update, context):
    cat = update.callback_query.data.replace("cat_", "")
    value = context.user_data["value"]
    mode = context.user_data["mode"]

    db["transactions"].append({
        "type": mode,
        "value": value,
        "category": cat,
        "date": now()
    })
    save_db(db)

    await update.callback_query.message.reply_text(
        f"✅ {mode.upper()} registrado: R$ {value:.2f} em {cat}"
    )

# ================= CATEGORIES =================
async def categories(update, context):
    keyboard = [
        [InlineKeyboardButton("➕ Adicionar Categoria", callback_data="add_cat")]
    ]
    await update.callback_query.message.reply_text("📂 Categorias", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_category(update, context):
    context.user_data["adding_category"] = True
    await update.callback_query.message.reply_text("Digite: tipo nome\nEx: gasto Mercado")

async def handle_category(update, context):
    if not context.user_data.get("adding_category"):
        return

    try:
        tipo, nome = update.message.text.split(" ", 1)
        db["categories"][tipo].append(nome)
        save_db(db)
        await update.message.reply_text(f"✅ Categoria adicionada: {nome}")
    except:
        await update.message.reply_text("❌ Formato inválido.")

    context.user_data["adding_category"] = False

# ================= FIXED COSTS =================
async def fixed(update, context):
    context.user_data["adding_fixed"] = True
    await update.callback_query.message.reply_text("Digite custo fixo:\nNome Valor\nEx: Netflix 45")

async def handle_fixed(update, context):
    if not context.user_data.get("adding_fixed"):
        return

    try:
        name, value = update.message.text.rsplit(" ", 1)
        db["fixed_costs"].append({
            "name": name,
            "value": float(value),
            "date": now()
        })
        save_db(db)
        await update.message.reply_text("✅ Custo fixo salvo.")
    except:
        await update.message.reply_text("❌ Erro ao salvar.")

    context.user_data["adding_fixed"] = False

# ================= GOALS =================
async def goals(update, context):
    context.user_data["adding_goal"] = True
    await update.callback_query.message.reply_text("Digite meta:\nNome Valor\nEx: iFood 300")

async def handle_goal(update, context):
    if not context.user_data.get("adding_goal"):
        return

    try:
        name, value = update.message.text.rsplit(" ", 1)
        db["goals"].append({
            "name": name,
            "limit": float(value),
            "spent": 0
        })
        save_db(db)
        await update.message.reply_text("🎯 Meta criada.")
    except:
        await update.message.reply_text("❌ Erro.")

    context.user_data["adding_goal"] = False

# ================= REPORT =================
async def report(update, context):
    gastos = [t for t in db["transactions"] if t["type"] == "gasto"]
    ganhos = [t for t in db["transactions"] if t["type"] == "ganho"]

    total_gasto = sum(t["value"] for t in gastos)
    total_ganho = sum(t["value"] for t in ganhos)

    cat_summary = {}
    for t in gastos:
        cat_summary[t["category"]] = cat_summary.get(t["category"], 0) + t["value"]

    text = "📊 **RELATÓRIO MONSTRO**\n\n"
    text += f"💰 Ganhos: R$ {total_ganho:.2f}\n"
    text += f"💸 Gastos: R$ {total_gasto:.2f}\n"
    text += f"📈 Saldo: R$ {total_ganho - total_gasto:.2f}\n\n"

    text += "📂 Gastos por categoria:\n"
    for c, v in cat_summary.items():
        text += f"• {c}: R$ {v:.2f}\n"

    if total_gasto > total_ganho:
        text += "\n⚠️ Gastando mais que ganha. Vai comer ovo esse mês 🥚"

    await update.callback_query.message.reply_text(text, parse_mode="Markdown")

# ================= TRASH =================
async def trash(update, context):
    db["transactions"].clear()
    db["goals"].clear()
    db["fixed_costs"].clear()
    save_db(db)

    await update.callback_query.message.reply_text("🗑️ Tudo limpo. Reset financeiro.")

# ================= ANTI SLEEP =================
async def heartbeat():
    while True:
        logging.info("🟢 Bot vivo — anti sleep ativo")
        await asyncio.sleep(300)

# ================= MAIN =================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(add_income, pattern="add_income"))
    app.add_handler(CallbackQueryHandler(add_expense, pattern="add_expense"))
    app.add_handler(CallbackQueryHandler(categories, pattern="categories"))
    app.add_handler(CallbackQueryHandler(add_category, pattern="add_cat"))
    app.add_handler(CallbackQueryHandler(fixed, pattern="fixed"))
    app.add_handler(CallbackQueryHandler(goals, pattern="goals"))
    app.add_handler(CallbackQueryHandler(report, pattern="report"))
    app.add_handler(CallbackQueryHandler(trash, pattern="trash"))

    app.add_handler(CallbackQueryHandler(set_category, pattern="cat_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_category))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fixed))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_goal))

    asyncio.create_task(heartbeat())

    print("🤖 BOT MONSTRO ONLINE")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
