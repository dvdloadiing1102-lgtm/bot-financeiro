# main.py - VERSÃO SUPER SIMPLIFICADA (SEM KEEP-ALIVE)

import os
import json
import logging
import asyncio
from datetime import datetime

# Tenta importar. Se falhar, o log da Render vai mostrar o erro de módulo.
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError as e:
    print(f"ERRO CRÍTICO: Dependência não encontrada. Verifique o requirements.txt. Erro: {e}")
    # Sai do script se a biblioteca principal não estiver lá.
    exit()


# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN ou BOT_TOKEN na Render")

DB_FILE = "db.json"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= DB =================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"transactions": [], "categories": {"gasto": [], "ganho": [], "fixo": []}, "goals": [], "fixed_costs": [], "users": {}}
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"transactions": [], "categories": {"gasto": [], "ganho": [], "fixo": []}, "goals": [], "fixed_costs": [], "users": {}}

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

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

# ================= HANDLERS (Funções do Bot) =================
# (As funções do bot como 'start', 'add_income', 'handle_message', etc. continuam aqui)
# Para economizar espaço, não vou repetir todas, mas elas devem estar aqui.
# O código abaixo é um resumo, certifique-se de que as funções do seu bot estejam presentes.

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

# ... (COLE AQUI TODAS AS SUAS OUTRAS FUNÇÕES DE HANDLER: add_income, add_expense, report, handle_message, etc.)
# É importante que todas as funções que você usa nos handlers estejam aqui.
# Vou colocar a handle_message como exemplo, pois é a mais complexa.

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state, mode, text = context.user_data.get("state"), context.user_data.get("mode"), update.message.text
    if mode in ["ganho", "gasto"]:
        try:
            value = float(text.replace(",", ".")); context.user_data["value"] = value
            cats = db["categories"].get(mode, [])
            if not cats:
                await update.message.reply_text("❌ Nenhuma categoria cadastrada.", reply_markup=get_menu()); context.user_data.clear(); return
            keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats] + [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
            await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(keyboard))
            context.user_data["mode"] = None
        except ValueError: await update.message.reply_text("❌ Valor inválido.")
        return
    # ... (resto da lógica da handle_message)
    else:
        await update.message.reply_text("🤖 Não entendi. Use os botões.", reply_markup=get_menu())
    context.user_data.clear()


# ================= MAIN =================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Adicione todos os seus handlers aqui
    # app.add_handler(...)
    # app.add_handler(...)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    # ... adicione todos os outros handlers aqui ...
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


    logger.info("🤖 BOT FINANCEIRO INICIANDO...")
    
    # Inicia o bot.
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # A forma mais simples e direta de rodar o bot.
    asyncio.run(main())

