import os
import json
import logging
import asyncio
import threading
import time
import urllib.request
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN ou BOT_TOKEN na Render")

DB_FILE = "db.json"
RENDER_URL = os.getenv("RENDER_URL", "https://bot-financeiro-hu1p.onrender.com")

logging.basicConfig(level=logging.INFO)

# ================= KEEP ALIVE =================

def keep_alive():
    """Função para manter o bot acordado no Render"""
    while True:
        try:
            time.sleep(300)  # A cada 5 minutos
            urllib.request.urlopen(RENDER_URL, timeout=5)
            print(f"✅ Keep-alive ping realizado!")
        except Exception as e:
            print(f"⚠️ Keep-alive: {e}")

# ================= DB =================

def load_db():
    if not os.path.exists(DB_FILE):
        return {
            "transactions": [],
            "categories": {"gasto": [], "ganho": [], "fixo": []},
            "goals": [],
            "fixed_costs": [],
            "users": {}
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

# ================= MENU =================

def get_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Ganho", callback_data="add_income")],
        [InlineKeyboardButton("💸 Gasto", callback_data="add_expense")],
        [InlineKeyboardButton("📂 Categorias", callback_data="categories")],
        [InlineKeyboardButton("📌 Custos Fixos", callback_data="fixed")],
        [InlineKeyboardButton("🎯 Metas", callback_data="goals")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report")],
        [InlineKeyboardButton("🗑️ Deletar", callback_data="trash")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in db["users"]:
        db["users"][str(uid)] = {"mode": None, "value": 0}
        save_db(db)
    
    await update.message.reply_text(
        "🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

# ================= MENU VOLTAR =================

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

# ================= ADD TRANSACTIONS =================

async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    context.user_data["mode"] = "ganho"
    context.user_data["uid"] = uid
    
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
    await update.callback_query.edit_message_text(
        "💰 Digite o valor do GANHO:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    context.user_data["mode"] = "gasto"
    context.user_data["uid"] = uid
    
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
    await update.callback_query.edit_message_text(
        "💸 Digite o valor do GASTO:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "mode" not in context.user_data:
        return
    
    try:
        value = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return

    mode = context.user_data.get("mode")
    context.user_data["value"] = value

    cats = db["categories"].get(mode, [])
    if not cats:
        await update.message.reply_text("❌ Nenhuma categoria cadastrada.")
        return

    keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
    keyboard.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu")])
    await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(keyboard))

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = update.callback_query.data.replace("cat_", "")
    value = context.user_data.get("value", 0)
    mode = context.user_data.get("mode")

    if not mode or value == 0:
        await update.callback_query.answer("Erro ao processar", show_alert=True)
        return

    db["transactions"].append({
        "type": mode,
        "value": value,
        "category": cat,
        "date": now()
    })
    save_db(db)

    await update.callback_query.edit_message_text(
        f"✅ {mode.upper()} registrado!\n💰 R$ {value:.2f} em {cat}",
        reply_markup=get_menu()
    )
    
    context.user_data["mode"] = None
    context.user_data["value"] = 0

# ================= CATEGORIES =================

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Adicionar Categoria", callback_data="add_cat")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]
    ]
    await update.callback_query.edit_message_text(
        "📂 Categorias",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adding_category"] = True
    buttons = [[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]
    await update.callback_query.edit_message_text(
        "Digite: tipo nome\nEx: gasto Mercado\n\nTipos: gasto, ganho, fixo",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("adding_category"):
        return

    try:
        parts = update.message.text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato inválido. Use: tipo nome")
            return
        
        tipo, nome = parts
        if tipo not in db["categories"]:
            await update.message.reply_text(f"❌ Tipo inválido. Use: gasto, ganho ou fixo")
            return
        
        db["categories"][tipo].append(nome)
        save_db(db)
        await update.message.reply_text(f"✅ Categoria adicionada: {nome}")
        context.user_data["adding_category"] = False
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {str(e)}")

# ================= FIXED COSTS =================

async def fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adding_fixed"] = True
    buttons = [[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]
    await update.callback_query.edit_message_text(
        "Digite custo fixo:\nNome Valor\nEx: Netflix 45",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("adding_fixed"):
        return

    try:
        parts = update.message.text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato inválido. Use: Nome Valor")
            return
        
        name, value = parts
        db["fixed_costs"].append({
            "name": name,
            "value": float(value),
            "date": now()
        })
        save_db(db)
        await update.message.reply_text("✅ Custo fixo salvo.")
        context.user_data["adding_fixed"] = False
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {str(e)}")

# ================= GOALS =================

async def goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adding_goal"] = True
    buttons = [[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]
    await update.callback_query.edit_message_text(
        "Digite meta:\nNome Valor\nEx: iFood 300",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("adding_goal"):
        return

    try:
        parts = update.message.text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato inválido. Use: Nome Valor")
            return
        
        name, value = parts
        db["goals"].append({
            "name": name,
            "limit": float(value),
            "spent": 0,
            "date": now()
        })
        save_db(db)
        await update.message.reply_text("🎯 Meta criada.")
        context.user_data["adding_goal"] = False
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {str(e)}")

# ================= REPORT =================

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gastos = [t for t in db["transactions"] if t["type"] == "gasto"]
    ganhos = [t for t in db["transactions"] if t["type"] == "ganho"]

    total_gasto = sum(t["value"] for t in gastos)
    total_ganho = sum(t["value"] for t in ganhos)

    cat_summary = {}
    for t in gastos:
        cat_summary[t["category"]] = cat_summary.get(t["category"], 0) + t["value"]

    text = "📊 **RELATÓRIO DETALHADO**\n\n"
    text += f"💰 Ganhos: R$ {total_ganho:.2f}\n"
    text += f"💸 Gastos: R$ {total_gasto:.2f}\n"
    text += f"📈 Saldo: R$ {total_ganho - total_gasto:.2f}\n\n"

    text += "📂 Gastos por categoria:\n"
    for c, v in cat_summary.items():
        text += f"• {c}: R$ {v:.2f}\n"

    if total_gasto > total_ganho:
        text += "\n⚠️ Gastando mais que ganha!"

    await update.callback_query.edit_message_text(
        text,
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

# ================= TRASH =================

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db["transactions"].clear()
    db["goals"].clear()
    db["fixed_costs"].clear()
    save_db(db)

    await update.callback_query.edit_message_text(
        "🗑️ Tudo deletado. Reset financeiro.",
        reply_markup=get_menu()
    )

# ================= MAIN =================

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    
    app.add_handler(CallbackQueryHandler(menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(add_income, pattern="^add_income$"))
    app.add_handler(CallbackQueryHandler(add_expense, pattern="^add_expense$"))
    app.add_handler(CallbackQueryHandler(categories, pattern="^categories$"))
    app.add_handler(CallbackQueryHandler(add_category, pattern="^add_cat$"))
    app.add_handler(CallbackQueryHandler(fixed, pattern="^fixed$"))
    app.add_handler(CallbackQueryHandler(goals, pattern="^goals$"))
    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(trash, pattern="^trash$"))
    app.add_handler(CallbackQueryHandler(set_category, pattern="^cat_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_value))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_category))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fixed))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_goal))

    print("🤖 BOT FINANCEIRO ONLINE - KEEP ALIVE ATIVADO")
    await app.run_polling()

if __name__ == "__main__":
    # Inicia keep-alive em thread separada
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    print("✅ Keep-Alive iniciado!")
    
    # Inicia o bot
    asyncio.run(main())
