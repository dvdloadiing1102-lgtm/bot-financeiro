# main.py ATUALIZADO PARA v21+

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

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN ou BOT_TOKEN na Render")

DB_FILE = "db.json"
RENDER_URL = os.getenv("RENDER_URL")
if not RENDER_URL:
    print("⚠️ AVISO: RENDER_URL não está configurada. O keep-alive não funcionará.")


logging.basicConfig(level=logging.INFO)

# ================= KEEP ALIVE =================

def keep_alive():
    """Função para manter o bot acordado no Render"""
    if not RENDER_URL:
        print("ℹ️ Keep-alive desativado pois RENDER_URL não foi definida.")
        return
        
    while True:
        try:
            time.sleep(300)  # A cada 5 minutos
            with urllib.request.urlopen(RENDER_URL, timeout=10) as response:
                print(f"✅ Keep-alive ping realizado! Status: {response.status}")
        except Exception as e:
            print(f"⚠️ Erro no Keep-alive: {e}")

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
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {
            "transactions": [],
            "categories": {"gasto": [], "ganho": [], "fixo": []},
            "goals": [],
            "fixed_costs": [],
            "users": {}
        }


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
    
    # Limpa qualquer estado anterior ao iniciar
    context.user_data.clear()
    
    await update.message.reply_text(
        "🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Limpa qualquer estado anterior ao voltar para o menu
    context.user_data.clear()

    await query.edit_message_text(
        "🤖 **BOT FINANCEIRO PREMIUM**\nEscolha uma opção:",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

# ================= TRANSACTIONS =================

async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = "ganho"
    
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
    await query.edit_message_text(
        "💰 Digite o valor do GANHO:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = "gasto"
    
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
    await query.edit_message_text(
        "💸 Digite o valor do GASTO:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cat = query.data.replace("cat_", "")
    value = context.user_data.get("value", 0)
    mode = context.user_data.get("mode")

    if not mode or value == 0:
        await query.edit_message_text("❌ Erro ao processar. Tente novamente.", reply_markup=get_menu())
        return

    db["transactions"].append({
        "type": mode,
        "value": value,
        "category": cat,
        "date": now()
    })
    save_db(db)

    await query.edit_message_text(
        f"✅ {mode.upper()} registrado!\n💰 R$ {value:.2f} em {cat}",
        reply_markup=get_menu()
    )
    context.user_data.clear()

# ================= CATEGORIES =================

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Adicionar Categoria", callback_data="add_cat")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]
    ]
    await query.edit_message_text(
        "📂 Gerenciar Categorias",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_category"
    buttons = [[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]
    await query.edit_message_text(
        "Digite: `tipo nome`\nEx: `gasto Mercado`\n\nTipos válidos: `gasto`, `ganho`, `fixo`",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ================= FIXED COSTS =================

async def fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_fixed"
    buttons = [[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]
    await query.edit_message_text(
        "Digite o custo fixo:\n`Nome Valor`\nEx: `Netflix 45.90`",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ================= GOALS =================

async def goals_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_goal"
    buttons = [[InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]]
    await query.edit_message_text(
        "Digite a sua meta:\n`Nome Limite`\nEx: `iFood 300`",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ================= REPORT =================

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
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

    if cat_summary:
        text += "📂 Gastos por categoria:\n"
        for c, v in sorted(cat_summary.items(), key=lambda item: item[1], reverse=True):
            text += f"• {c}: R$ {v:.2f}\n"
    else:
        text += "📂 Nenhum gasto por categoria registrado.\n"

    if total_gasto > total_ganho:
        text += "\n⚠️ **Atenção!** Você está gastando mais do que ganha!"

    await query.edit_message_text(
        text,
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

# ================= TRASH =================

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    db["transactions"].clear()
    db["goals"].clear()
    db["fixed_costs"].clear()
    save_db(db)

    await query.edit_message_text(
        "🗑️ Todos os registros financeiros foram deletados.",
        reply_markup=get_menu()
    )

# ================= UNIFIED MESSAGE HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Função única para tratar todas as mensagens de texto."""
    state = context.user_data.get("state")
    mode = context.user_data.get("mode")
    text = update.message.text

    # --- Lógica para adicionar valor de ganho/gasto ---
    if mode in ["ganho", "gasto"]:
        try:
            value = float(text.replace(",", "."))
            context.user_data["value"] = value

            cats = db["categories"].get(mode, [])
            if not cats:
                await update.message.reply_text("❌ Nenhuma categoria cadastrada para este tipo. Adicione uma primeiro.", reply_markup=get_menu())
                context.user_data.clear()
                return

            keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
            keyboard.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu")])
            await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(keyboard))
            # Muda o estado para não reprocessar esta mensagem
            context.user_data["mode"] = None 
            
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Por favor, digite apenas números (ex: 15.50).")
        return

    # --- Lógica para adicionar Categoria, Custo Fixo ou Meta ---
    if state == "adding_category":
        parts = text.split(" ", 1)
        if len(parts) < 2 or parts[0].lower() not in db["categories"]:
            await update.message.reply_text("❌ Formato inválido. Use: `tipo nome` (ex: `gasto Mercado`). Tipos: `gasto`, `ganho`, `fixo`.", parse_mode="Markdown")
            return
        
        tipo, nome = parts[0].lower(), parts[1]
        db["categories"][tipo].append(nome)
        save_db(db)
        await update.message.reply_text(f"✅ Categoria '{nome}' adicionada em '{tipo}'.", reply_markup=get_menu())

    elif state == "adding_fixed":
        parts = text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato inválido. Use: `Nome Valor` (ex: `Netflix 45.90`).", parse_mode="Markdown")
            return
        
        try:
            name, value_str = parts
            value = float(value_str.replace(",", "."))
            db["fixed_costs"].append({"name": name, "value": value, "date": now()})
            save_db(db)
            await update.message.reply_text("✅ Custo fixo salvo.", reply_markup=get_menu())
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. O formato é `Nome Valor`.", parse_mode="Markdown")

    elif state == "adding_goal":
        parts = text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato inválido. Use: `Nome Limite` (ex: `iFood 300`).", parse_mode="Markdown")
            return
            
        try:
            name, value_str = parts
            value = float(value_str.replace(",", "."))
            db["goals"].append({"name": name, "limit": value, "spent": 0, "date": now()})
            save_db(db)
            await update.message.reply_text("🎯 Meta criada.", reply_markup=get_menu())
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. O formato é `Nome Limite`.", parse_mode="Markdown")
    
    else:
        await update.message.reply_text("🤖 Não entendi. Por favor, use os botões do menu.", reply_markup=get_menu())

    # Limpa o estado após a ação ser concluída
    context.user_data.clear()


# ================= MAIN =================

async def main():
    # A v21+ usa o ApplicationBuilder para criar o app diretamente
    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers de Comando e Callback
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

    # Handler ÚNICO para todas as mensagens de texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 BOT FINANCEIRO ONLINE")
    
    # Na v21+, o run_polling é chamado diretamente pelo app
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    # Inicia keep-alive em thread separada
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    print("✅ Keep-Alive iniciado!")
    
    # Inicia o bot
    asyncio.run(main())

