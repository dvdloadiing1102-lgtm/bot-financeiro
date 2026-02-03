import os
import sys
import json
import logging
import uuid
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- AUTO-INSTALAÇÃO ---
try:
    import httpx
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
except ImportError:
    print("⚠️ Instalando dependências...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================

# 👇👇👇 SEU TOKEN AQUI 👇👇👇
TOKEN = "SEU_TOKEN_AQUI" 

DB_FILE = "finance_final.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= SERVIDOR WEB (ANTI-CRASH) =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"BOT ONLINE")
        
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=start_web_server, daemon=True).start()

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "Mercado"]
        },
        "fixed_items": [], 
        "goals": []
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS =================
# Estados da Conversa
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, NEW_CAT_NAME, ADD_FIXED, ADD_GOAL) = range(7)

def get_main_menu():
    kb = [
        [InlineKeyboardButton("📝 Registrar Novo", callback_data="start_reg")],
        [InlineKeyboardButton("📊 Relatório Rápido", callback_data="report_quick"),
         InlineKeyboardButton("🕵️ Análise Detalhada", callback_data="report_full")],
        [InlineKeyboardButton("📌 Fixos/Salários", callback_data="menu_fixed"),
         InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("🗑️ Gerenciar/Apagar", callback_data="menu_delete")],
        [InlineKeyboardButton("📦 Backup", callback_data="backup")]
    ]
    return InlineKeyboardMarkup(kb)

def get_cancel_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="cancel")]])

# ================= FUNÇÃO START (CORRIGIDA) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "🤖 **FINANCEIRO PRO**\nSelecione uma opção:"
    
    # Verifica se veio de um botão (Callback) ou comando de texto (/start)
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
        except:
            # Caso não dê para editar, envia nova mensagem
            await update.callback_query.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    
    return ConversationHandler.END

# ================= 1. FLUXO DE REGISTRO (REVISADO) =================

async def start_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("📉 É um GASTO", callback_data="type_gasto")],
        [InlineKeyboardButton("📈 É um GANHO", callback_data="type_ganho")],
        [InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]
    ]
    await query.edit_message_text("Passo 1/4: **O que você vai registrar?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_TYPE

async def reg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    tipo = query.data.split("_")[1]
    context.user_data["temp_type"] = tipo
    
    emoji = "💸" if tipo == "gasto" else "💰"
    await query.edit_message_text(
        f"{emoji} Passo 2/4: **Qual o valor?**\n\nDigite apenas números (ex: `25.50`).",
        reply_markup=get_cancel_btn(), parse_mode="Markdown"
    )
    return REG_VALUE

async def reg_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(',', '.')
    try:
        val = float(text)
        context.user_data["temp_value"] = val
        
        # Carrega categorias do banco
        tipo = context.user_data["temp_type"]
        cats = db["categories"].get(tipo, [])
        
        kb = []
        row = []
        for c in cats:
            row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
            if len(row) == 2: kb.append(row); row = []
        if row: kb.append(row)
        
        kb.append([InlineKeyboardButton("➕ Criar Nova Categoria", callback_data="new_cat")])
        kb.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")])
        
        await update.message.reply_text(f"Passo 3/4: **Escolha a Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_CAT
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 10.90):")
        return REG_VALUE

async def reg_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    # Se clicar em Nova Categoria
    if data == "new_cat":
        await query.edit_message_text("✍️ **Digite o nome da nova categoria:**")
        return NEW_CAT_NAME
    
    # Se escolher uma existente
    cat = data.replace("cat_", "")
    context.user_data["temp_cat"] = cat
    
    # Sugestões de descrição
    sugestoes = ["Uber", "iFood", "Mercado", "Aluguel", "Pix", "Cartão", "Salário", "Investimento"]
    kb = []
    row = []
    for s in sugestoes:
        row.append(InlineKeyboardButton(s, callback_data=f"desc_{s}"))
        if len(row) == 3: kb.append(row); row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("⏩ Pular Descrição", callback_data="desc_Sem Descrição")])
    
    await query.edit_message_text(
        f"Passo 4/4: **Descrição para '{cat}'**\nClique numa sugestão ou DIGITE o nome (ex: Padaria):",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )
    return REG_DESC

async def new_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.message.text
    tipo = context.user_data["temp_type"]
    
    if nome not in db["categories"][tipo]:
        db["categories"][tipo].append(nome)
        save_db(db)
        
    context.user_data["temp_cat"] = nome
    kb = [[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]
    await update.message.reply_text(f"✅ Categoria **{nome}** criada!\nAgora a descrição:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_DESC

async def reg_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Lida com botão ou texto
    if update.callback_query:
        query = update.callback_query; await query.answer()
        desc = query.data.replace("desc_", "")
        reply_func = query.edit_message_text
    else:
        desc = update.message.text
        reply_func = update.message.reply_text

    item = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["temp_type"],
        "value": context.user_data["temp_value"],
        "category": context.user_data["temp_cat"],
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    db["transactions"].append(item)
    save_db(db)
    
    msg = f"✅ **Registrado!**\n{item['type'].upper()}: R$ {item['value']:.2f}\n📂 {item['category']} | 📝 {desc}"
    await reply_func(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

# ================= 2. OUTROS MENUS =================

async def menu_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("💲 Apagar Últimas Transações", callback_data="del_list_trans")],
        [InlineKeyboardButton("📂 Apagar Categoria", callback_data="del_list_cat")],
        [InlineKeyboardButton("📌 Apagar Item Fixo", callback_data="del_list_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]
    ]
    await query.edit_message_text("🗑️ **Central de Exclusão**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    # Lógica de exclusão simplificada para não estender demais
    if data == "del_list_trans":
        kb = []
        for t in reversed(db["transactions"][-5:]):
            kb.append([InlineKeyboardButton(f"❌ R$ {t['value']} - {t['category']}", callback_data=f"kill_id_{t['id']}")])
        kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])
        await query.edit_message_text("Apagar qual?", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data.startswith("kill_id_"):
        tid = data.replace("kill_id_", "")
        db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
        save_db(db)
        await query.edit_message_text("✅ Apagado!", reply_markup=get_main_menu())
        
    elif data == "menu_delete":
        await menu_delete(update, context)

async def menu_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Novo Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    
    text = "📌 **SEUS FIXOS:**\n"
    for f in db["fixed_items"]: text += f"- {f['name']}: R$ {f['value']:.2f}\n"
            
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `Tipo Nome Valor`\nEx: `gasto Internet 100`", reply_markup=get_cancel_btn(), parse_mode="Markdown")
    return ADD_FIXED

async def add_fixed_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split(" ")
        db["fixed_items"].append({"type": parts[0].lower(), "name": " ".join(parts[1:-1]), "value": float(parts[-1])})
        save_db(db)
        await update.message.reply_text("✅ Salvo!", reply_markup=get_main_menu())
    except:
        await update.message.reply_text("Erro. Use: `ganho Salário 2000`")
    return ConversationHandler.END

async def report_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    text = "🕵️ **ANÁLISE DETALHADA**\n\n"
    for t in reversed(db["transactions"][-15:]):
        text += f"• {t['category']} | {t['description']}: R$ {t['value']:.2f}\n"
    await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

async def report_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    # Soma simples para exemplo
    total = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho') - sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    await query.edit_message_text(f"📊 Saldo Atual: R$ {total:.2f}", reply_markup=get_main_menu())

async def menu_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    text = "🎯 **METAS:**\n"
    for g in db["goals"]: text += f"- {g['category']}: R$ {g['limit']}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `Categoria Valor`\nEx: `Lazer 500`", reply_markup=get_cancel_btn(), parse_mode="Markdown")
    return ADD_GOAL

async def add_goal_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cat, val = update.message.text.rsplit(" ", 1)
        db["goals"].append({"category": cat, "limit": float(val)})
        save_db(db)
        await update.message.reply_text("✅ Meta salva!", reply_markup=get_main_menu())
    except:
        await update.message.reply_text("Erro.")
    return ConversationHandler.END

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await update.effective_message.reply_document(open(DB_FILE, "rb"), caption="📦 Backup")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END

# ================= MAIN =================
if __name__ == "__main__":
    if "SEU_TOKEN" in TOKEN:
        print("❌ ERRO: Configure o TOKEN na linha 25!")
        sys.exit()

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Conversa de Registro (CORAÇÃO DO BOT)
    conv_reg = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type, pattern="^type_")],
            REG_VALUE: [MessageHandler(filters.TEXT, reg_value)],
            REG_CAT: [CallbackQueryHandler(reg_cat, pattern="^cat_|^new_cat$")],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT, new_cat_save)],
            REG_DESC: [CallbackQueryHandler(reg_finish, pattern="^desc_"), MessageHandler(filters.TEXT, reg_finish)]
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    
    # Outros Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_reg)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")],
        states={ADD_FIXED: [MessageHandler(filters.TEXT, add_fixed_save)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_goal_start, pattern="^add_goal_start$")],
        states={ADD_GOAL: [MessageHandler(filters.TEXT, add_goal_save)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    ))
    
    # Menus
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$")) # Voltar genérico
    app.add_handler(CallbackQueryHandler(report_quick, pattern="^report_quick$"))
    app.add_handler(CallbackQueryHandler(report_full, pattern="^report_full$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_handler, pattern="^(del_list_|kill_)"))
    app.add_handler(CallbackQueryHandler(backup, pattern="^backup$"))
    
    print("Bot Iniciado...")
    app.run_polling()