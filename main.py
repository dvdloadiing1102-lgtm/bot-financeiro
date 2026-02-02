# main.py - VERSÃO COMPLETA E CORRIGIDA

import os
import json
import logging
import asyncio
import httpx  # Usado para o keep-alive assíncrono
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN ou BOT_TOKEN na Render")

DB_FILE = "db.json"
RENDER_URL = os.getenv("RENDER_URL")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= KEEP ALIVE ASSÍNCRONO =================

async def keep_alive_async():
    """Função assíncrona para manter o bot acordado no Render."""
    if not RENDER_URL:
        logger.info("Keep-alive desativado pois RENDER_URL não foi definida.")
        return
        
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Espera 5 minutos (300 segundos) de forma assíncrona
                await asyncio.sleep(300)
                
                response = await client.get(RENDER_URL, timeout=10)
                logger.info(f"Keep-alive ping realizado! Status: {response.status_code}")

            except Exception as e:
                logger.error(f"Erro no Keep-alive: {e}")

# ================= DB =================

def load_db():
    if not os.path.exists(DB_FILE):
        return {"transactions": [], "categories": {"gasto": [], "ganho": [], "fixo": []}, "goals": [], "fixed_costs": [], "users": {}}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"transactions": [], "categories": {"gasto": [], "ganho": [], "fixo": []}, "goals": [], "fixed_costs": [], "users": {}}

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
    ])

# ================= START & MENU =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"mode": None}
        save_db(db)
    context.user_data.clear()
    await update.message.reply_text("🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

# ================= TRANSACTIONS =================

async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = "ganho"
    await query.edit_message_text("💰 Digite o valor do GANHO:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]))

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = "gasto"
    await query.edit_message_text("💸 Digite o valor do GASTO:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]))

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat, value, mode = query.data.replace("cat_", ""), context.user_data.get("value", 0), context.user_data.get("mode")
    if not mode or value == 0:
        await query.edit_message_text("❌ Erro ao processar. Tente novamente.", reply_markup=get_menu())
        return
    db["transactions"].append({"type": mode, "value": value, "category": cat, "date": now()})
    save_db(db)
    await query.edit_message_text(f"✅ {mode.upper()} registrado!\n💰 R$ {value:.2f} em {cat}", reply_markup=get_menu())
    context.user_data.clear()

# ================= CATEGORIES, FIXED COSTS, GOALS (PROMPTS) =================

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📂 Gerenciar Categorias", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Adicionar Categoria", callback_data="add_cat")], [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]))

async def add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_category"
    await query.edit_message_text("Digite: `tipo nome`\nEx: `gasto Mercado`\n\nTipos: `gasto`, `ganho`, `fixo`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]), parse_mode="Markdown")

async def fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_fixed"
    await query.edit_message_text("Digite o custo fixo:\n`Nome Valor`\nEx: `Netflix 45.90`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]), parse_mode="Markdown")

async def goals_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_goal"
    await query.edit_message_text("Digite a sua meta:\n`Nome Limite`\nEx: `iFood 300`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]), parse_mode="Markdown")

# ================= REPORT & TRASH =================

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gastos, ganhos = [t for t in db["transactions"] if t["type"] == "gasto"], [t for t in db["transactions"] if t["type"] == "ganho"]
    total_gasto, total_ganho = sum(t["value"] for t in gastos), sum(t["value"] for t in ganhos)
    cat_summary = {}
    for t in gastos: cat_summary[t["category"]] = cat_summary.get(t["category"], 0) + t["value"]
    text = f"📊 **RELATÓRIO**\n\n💰 Ganhos: R$ {total_ganho:.2f}\n💸 Gastos: R$ {total_gasto:.2f}\n📈 Saldo: R$ {total_ganho - total_gasto:.2f}\n\n"
    if cat_summary:
        text += "📂 Gastos por categoria:\n"
        for c, v in sorted(cat_summary.items(), key=lambda item: item[1], reverse=True): text += f"• {c}: R$ {v:.2f}\n"
    if total_gasto > total_ganho: text += "\n⚠️ **Atenção!** Você está gastando mais do que ganha!"
    await query.edit_message_text(text, reply_markup=get_menu(), parse_mode="Markdown")

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db["transactions"].clear(); db["goals"].clear(); db["fixed_costs"].clear()
    save_db(db)
    await query.edit_message_text("🗑️ Todos os registros foram deletados.", reply_markup=get_menu())

# ================= UNIFIED MESSAGE HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state, mode, text = context.user_data.get("state"), context.user_data.get("mode"), update.message.text
    
    if mode in ["ganho", "gasto"]:
        try:
            value = float(text.replace(",", "."))
            context.user_data["value"] = value
            cats = db["categories"].get(mode, [])
            if not cats:
                await update.message.reply_text("❌ Nenhuma categoria cadastrada. Adicione uma primeiro.", reply_markup=get_menu())
                context.user_data.clear()
                return
            keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats] + [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
            await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(keyboard))
            context.user_data["mode"] = None
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 15.50).")
        return

    if state == "adding_category":
        parts = text.split(" ", 1)
        if len(parts) < 2 or parts[0].lower() not in db["categories"]:
            await update.message.reply_text("❌ Formato inválido. Use: `tipo nome` (ex: `gasto Mercado`).", parse_mode="Markdown")
            return
        tipo, nome = parts[0].lower(), parts[1]
        db["categories"][tipo].append(nome); save_db(db)
        await update.message.reply_text(f"✅ Categoria '{nome}' adicionada.", reply_markup=get_menu())

    elif state == "adding_fixed" or state == "adding_goal":
        parts = text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text(f"❌ Formato inválido. Use: `Nome {'Valor' if state == 'adding_fixed' else 'Limite'}`.", parse_mode="Markdown")
            return
        try:
            name, value_str = parts
            value = float(value_str.replace(",", "."))
            if state == "adding_fixed":
                db["fixed_costs"].append({"name": name, "value": value, "date": now()}); save_db(db)
                await update.message.reply_text("✅ Custo fixo salvo.", reply_markup=get_menu())
            else:
                db["goals"].append({"name": name, "limit": value, "spent": 0, "date": now()}); save_db(db)
                await update.message.reply_text("🎯 Meta criada.", reply_markup=get_menu())
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. O formato é `Nome Valor`.", parse_mode="Markdown")
    
    else:
        await update.message.reply_text("🤖 Não entendi. Por favor, use os botões do menu.", reply_markup=get_menu())

    context.user_data.clear()

# ================= MAIN =================

async def main():
    if RENDER_URL:
        asyncio.create_task(keep_alive_async())
        logger.info("Keep-Alive assíncrono agendado.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(add_income, pattern="^add_income$"))
    app.add_handler(CallbackQueryHandler(add_expense, pattern="^add_expense$"))
    app.add_handler(CallbackQueryHandler(categories, pattern="^categories$"))
    app.add_handler(CallbackQueryHandler(add_category_prompt, pattern="^add_cat$"))
    app.add_handler(CallbackQueryHandler(fixed_prompt, pattern="^fixed$"))
    app.add_handler(CallbackQueryHandler(goals_prompt, pattern="^goals$"))
    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(trash, pattern="^trash$"))
    app.add_handler(CallbackQueryHandler(set_category, pattern="^cat_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 BOT FINANCEIRO ONLINE")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
