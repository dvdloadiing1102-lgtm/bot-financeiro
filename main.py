# main.py - VERSÃO ORIGINAL JSON (ESTÁVEL)

import os
import sys
import subprocess
import json
import logging
import asyncio
from datetime import datetime

# --- BLOCO DE AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
try:
    import httpx
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("⚠️ Dependências não encontradas. Instalando...")
    try:
        # Instala python-telegram-bot e httpx (necessário para este código)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx"])
        print("✅ Dependências instaladas. Reiniciando...")
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        print(f"❌ Falha ao instalar: {e}")
        sys.exit(1)

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL") # Opcional, para manter vivo
DB_FILE = "db.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not TOKEN:
    print("❌ ERRO: Token não encontrado.")

# ================= SISTEMA DE BANCO DE DADOS (JSON) =================
def load_db():
    # Cria estrutura padrão se o arquivo não existir
    default_db = {
        "transactions": [], 
        "categories": {"gasto": [], "ganho": [], "fixo": []}, 
        "goals": [], 
        "fixed_costs": [], 
        "users": {}
    }
    if not os.path.exists(DB_FILE):
        return default_db
    try:
        with open(DB_FILE, "r") as f: 
            return json.load(f)
    except:
        return default_db

def save_db(data):
    with open(DB_FILE, "w") as f: 
        json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS =================
def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

# ================= KEEP ALIVE (Para Render) =================
async def keep_alive_async():
    if not RENDER_URL:
        return
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await asyncio.sleep(600) # Ping a cada 10 min
                await client.get(RENDER_URL, timeout=10)
            except: 
                pass

# ================= MENU PRINCIPAL (Layout Clássico) =================
def get_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Ganho", callback_data="add_income"),
         InlineKeyboardButton("💸 Gasto", callback_data="add_expense")],
        
        [InlineKeyboardButton("📂 Categorias", callback_data="categories"),
         InlineKeyboardButton("📌 Custos Fixos", callback_data="fixed")],
        
        [InlineKeyboardButton("🎯 Metas", callback_data="goals"),
         InlineKeyboardButton("📊 Relatório", callback_data="report")],
        
        [InlineKeyboardButton("🗑️ Deletar Tudo", callback_data="trash")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]])

# ================= FUNÇÕES DO BOT (HANDLERS) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"mode": None}
        save_db(db)
    context.user_data.clear()
    await update.message.reply_text("🤖 **BOT FINANCEIRO (JSON)**\nEscolha uma opção:", reply_markup=get_menu(), parse_mode="Markdown")

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🤖 **MENU PRINCIPAL**", reply_markup=get_menu(), parse_mode="Markdown")

# --- Fluxo de Valores ---
async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["mode"] = "ganho"
    await query.edit_message_text("💰 Digite o valor do **GANHO**:", reply_markup=get_back_btn(), parse_mode="Markdown")

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["mode"] = "gasto"
    await query.edit_message_text("💸 Digite o valor do **GASTO**:", reply_markup=get_back_btn(), parse_mode="Markdown")

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cat = query.data.replace("cat_", "")
    value = context.user_data.get("value", 0)
    mode = context.user_data.get("mode")
    
    if not mode or value == 0:
        await query.edit_message_text("❌ Erro. Tente novamente.", reply_markup=get_menu())
        return
        
    db["transactions"].append({"type": mode, "value": value, "category": cat, "date": now()})
    save_db(db)
    
    await query.edit_message_text(f"✅ {mode.upper()} de R$ {value:.2f} registrado em **{cat}**!", reply_markup=get_menu(), parse_mode="Markdown")
    context.user_data.clear()

# --- Gerenciamento ---
async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Criar Categoria", callback_data="add_cat")], [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]]
    await query.edit_message_text("📂 **Categorias**\nAdicione novas categorias personalizadas.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_category"
    await query.edit_message_text("Digite: `tipo nome`\nEx: `gasto Mercado` ou `ganho Freelance`", reply_markup=get_back_btn(), parse_mode="Markdown")

async def fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_fixed"
    await query.edit_message_text("Digite o custo fixo:\n`Nome Valor`\nEx: `Netflix 45.90`", reply_markup=get_back_btn(), parse_mode="Markdown")

async def goals_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_goal"
    await query.edit_message_text("Digite a meta:\n`Nome Valor`\nEx: `Lazer 200`", reply_markup=get_back_btn(), parse_mode="Markdown")

# --- Relatório ---
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    
    gastos = [t for t in db["transactions"] if t["type"] == "gasto"]
    ganhos = [t for t in db["transactions"] if t["type"] == "ganho"]
    
    total_gasto = sum(t["value"] for t in gastos)
    total_ganho = sum(t["value"] for t in ganhos)
    saldo = total_ganho - total_gasto
    
    # Resumo por categoria
    cat_summary = {}
    for t in gastos:
        cat = t["category"]
        cat_summary[cat] = cat_summary.get(cat, 0) + t["value"]
        
    text = f"📊 **RELATÓRIO**\n\n💰 Entradas: R$ {total_ganho:.2f}\n💸 Saídas: R$ {total_gasto:.2f}\n📈 **Saldo: R$ {saldo:.2f}**\n\n"
    
    if cat_summary:
        text += "📂 **Gastos por Categoria:**\n"
        for c, v in sorted(cat_summary.items(), key=lambda item: item[1], reverse=True):
            text += f"• {c}: R$ {v:.2f}\n"
            
    if total_gasto > total_ganho:
        text += "\n⚠️ **Cuidado!** Você está gastando mais do que ganha."
        
    await query.edit_message_text(text, reply_markup=get_menu(), parse_mode="Markdown")

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    db["transactions"] = []
    db["goals"] = []
    db["fixed_costs"] = []
    save_db(db)
    await query.edit_message_text("🗑️ **LIXEIRA**\nTodos os dados foram apagados.", reply_markup=get_menu(), parse_mode="Markdown")

# --- Processador de Texto (Inputs) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    mode = context.user_data.get("mode")
    text = update.message.text
    
    # 1. Processar Valor (Gasto/Ganho)
    if mode in ["ganho", "gasto"]:
        try:
            value = float(text.replace(",", "."))
            context.user_data["value"] = value
            
            # Pega categorias do banco ou usa padrão
            cats = db["categories"].get(mode, [])
            if not cats: cats = ["Geral"]
            
            keyboard = []
            row = []
            for c in cats:
                row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            keyboard.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")])
            
            await update.message.reply_text(f"Valor: R$ {value:.2f}\nEscolha a categoria:", reply_markup=InlineKeyboardMarkup(keyboard))
            context.user_data["mode"] = None # Limpa modo para não duplicar
            
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return

    # 2. Processar Comandos de Texto (Criar Categoria, Meta, etc)
    if state in ["adding_category", "adding_fixed", "adding_goal"]:
        try:
            if state == "adding_category":
                parts = text.split(" ", 1)
                if len(parts) < 2: raise ValueError
                tipo, nome = parts[0].lower(), parts[1]
                if tipo not in ["gasto", "ganho", "fixo"]:
                    await update.message.reply_text("❌ Tipo inválido. Use 'gasto' ou 'ganho'.")
                    return
                
                if nome not in db["categories"][tipo]:
                    db["categories"][tipo].append(nome)
                    save_db(db)
                    await update.message.reply_text(f"✅ Categoria **{nome}** criada!", reply_markup=get_menu(), parse_mode="Markdown")
                
            elif state in ["adding_fixed", "adding_goal"]:
                parts = text.rsplit(" ", 1)
                if len(parts) < 2: raise ValueError
                name, val_str = parts[0], parts[1]
                val = float(val_str.replace(",", "."))
                
                if state == "adding_fixed":
                    db["fixed_costs"].append({"name": name, "value": val})
                    await update.message.reply_text(f"✅ Custo fixo **{name}** salvo.", reply_markup=get_menu(), parse_mode="Markdown")
                else:
                    db["goals"].append({"name": name, "limit": val})
                    await update.message.reply_text(f"🎯 Meta **{name}** definida.", reply_markup=get_menu(), parse_mode="Markdown")
                save_db(db)
                
        except ValueError:
            await update.message.reply_text("❌ Formato inválido. Tente: `Nome Valor` ou `tipo nome`.")
        
        context.user_data.clear()
        return

    # Se não entendeu
    await update.message.reply_text("❓ Não entendi. Use o menu.", reply_markup=get_menu())

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    if RENDER_URL:
        # Inicia loop paralelo para Keep Alive
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(keep_alive_async())
        
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Adicionando Handlers
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
    
    # Handler de texto genérico (último)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot Iniciado...")
    app.run_polling()
