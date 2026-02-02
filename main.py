# main.py - VERSÃO FINAL COM AUTO-INSTALAÇÃO

import os
import sys
import subprocess
import json
import logging

# --- BLOCO DE AUTO-INSTALAÇÃO ---
try:
    import httpx
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("Dependências não encontradas. Instalando...")
    try:
        # Instala as dependências do requirements.txt
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("Dependências instaladas. Reiniciando o script...")
        # Substitui o processo atual por um novo, reiniciando o script
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        print(f"Falha ao instalar dependências: {e}")
        sys.exit(1) # Sai se a instalação falhar

# --- O RESTO DO CÓDIGO (EXATAMENTE COMO ANTES) ---
import asyncio
from datetime import datetime

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
    if not RENDER_URL:
        logger.info("Keep-alive desativado pois RENDER_URL não foi definida.")
        return
    async with httpx.AsyncClient() as client:
        while True:
            try:
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"mode": None}; save_db(db)
    context.user_data.clear()
    await update.message.reply_text("🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["mode"] = "ganho"
    await query.edit_message_text("💰 Digite o valor do GANHO:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]))

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["mode"] = "gasto"
    await query.edit_message_text("💸 Digite o valor do GASTO:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]))

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cat, value, mode = query.data.replace("cat_", ""), context.user_data.get("value", 0), context.user_data.get("mode")
    if not mode or value == 0:
        await query.edit_message_text("❌ Erro ao processar.", reply_markup=get_menu()); return
    db["transactions"].append({"type": mode, "value": value, "category": cat, "date": now()}); save_db(db)
    await query.edit_message_text(f"✅ {mode.upper()} registrado!\n💰 R$ {value:.2f} em {cat}", reply_markup=get_menu())
    context.user_data.clear()

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📂 Gerenciar Categorias", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Adicionar Categoria", callback_data="add_cat")], [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]))

async def add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_category"
    await query.edit_message_text("Digite: `tipo nome`\nEx: `gasto Mercado`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]), parse_mode="Markdown")

async def fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_fixed"
    await query.edit_message_text("Digite o custo fixo:\n`Nome Valor`\nEx: `Netflix 45.90`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]), parse_mode="Markdown")

async def goals_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_goal"
    await query.edit_message_text("Digite a sua meta:\n`Nome Limite`\nEx: `iFood 300`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]), parse_mode="Markdown")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    gastos, ganhos = [t for t in db["transactions"] if t["type"] == "gasto"], [t for t in db["transactions"] if t["type"] == "ganho"]
    total_gasto, total_ganho = sum(t["value"] for t in gastos), sum(t["value"] for t in ganhos)
    cat_summary = {t["category"]: cat_summary.get(t["category"], 0) + t["value"] for t in gastos} if gastos else {}
    text = f"📊 **RELATÓRIO**\n\n💰 Ganhos: R$ {total_ganho:.2f}\n💸 Gastos: R$ {total_gasto:.2f}\n📈 Saldo: R$ {total_ganho - total_gasto:.2f}\n\n"
    if cat_summary:
        text += "📂 Gastos por categoria:\n"
        for c, v in sorted(cat_summary.items(), key=lambda item: item[1], reverse=True): text += f"• {c}: R$ {v:.2f}\n"
    if total_gasto > total_ganho: text += "\n⚠️ **Atenção!** Você está gastando mais do que ganha!"
    await query.edit_message_text(text, reply_markup=get_menu(), parse_mode="Markdown")

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    db["transactions"].clear(); db["goals"].clear(); db["fixed_costs"].clear(); save_db(db)
    await query.edit_message_text("🗑️ Todos os registros foram deletados.", reply_markup=get_menu())

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
    if state in ["adding_category", "adding_fixed", "adding_goal"]:
        parts = text.split(" ", 1) if state == "adding_category" else text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato inválido."); return
        try:
            if state == "adding_category":
                tipo, nome = parts[0].lower(), parts[1]
                if tipo not in db["categories"]: await update.message.reply_text("❌ Tipo inválido."); return
                db["categories"][tipo].append(nome); await update.message.reply_text(f"✅ Categoria '{nome}' adicionada.", reply_markup=get_menu())
            else:
                name, value_str = parts; value = float(value_str.replace(",", "."))
                if state == "adding_fixed":
                    db["fixed_costs"].append({"name": name, "value": value, "date": now()}); await update.message.reply_text("✅ Custo fixo salvo.", reply_markup=get_menu())
                else:
                    db["goals"].append({"name": name, "limit": value, "spent": 0, "date": now()}); await update.message.reply_text("🎯 Meta criada.", reply_markup=get_menu())
            save_db(db)
        except (ValueError, IndexError): await update.message.reply_text("❌ Erro no formato.")
    else:
        await update.message.reply_text("🤖 Não entendi. Use os botões.", reply_markup=get_menu())
    context.user_data.clear()

# ================= MAIN =================
async def main():
    if RENDER_URL:
        asyncio.create_task(keep_alive_async())
        logger.info("Keep-Alive assíncrono agendado.")
    app = ApplicationBuilder().token(TOKEN).build()
    handlers = [
        CommandHandler("start", start), CallbackQueryHandler(menu_callback, pattern="^menu$"),
        CallbackQueryHandler(add_income, pattern="^add_income$"), CallbackQueryHandler(add_expense, pattern="^add_expense$"),
        CallbackQueryHandler(categories, pattern="^categories$"), CallbackQueryHandler(add_category_prompt, pattern="^add_cat$"),
        CallbackQueryHandler(fixed_prompt, pattern="^fixed$"), CallbackQueryHandler(goals_prompt, pattern="^goals$"),
        CallbackQueryHandler(report, pattern="^report$"), CallbackQueryHandler(trash, pattern="^trash$"),
        CallbackQueryHandler(set_category, pattern="^cat_"), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    ]
    app.add_handlers(handlers)
    logger.info("🤖 BOT FINANCEIRO ONLINE")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "cannot close a running event loop" in str(e) or "loop is already running" in str(e):
            logger.warning("Loop de eventos já estava rodando. Ignorando erro de fechamento.")
        else:
            raise
