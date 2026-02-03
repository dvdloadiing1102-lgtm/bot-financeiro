import os
import sys
import json
import logging
import uuid
import threading
import time
from datetime import datetime
from flask import Flask

# Tenta importar, se falhar, avisa (No Render as libs já devem estar instaladas via requirements.txt)
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
except ImportError:
    print("❌ ERRO: Instale 'python-telegram-bot' e 'flask'.")
    sys.exit(1)

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
DB_FILE = "finance_v3.json"

# Configuração de Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
        [InlineKeyboardButton("🗑️ Apagar Itens", callback_data="menu_delete")],
        [InlineKeyboardButton("📦 Backup", callback_data="backup")]
    ]
    return InlineKeyboardMarkup(kb)

def get_cancel_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="cancel")]])

# ================= HANDLERS PRINCIPAIS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 **Bem-vindo ao Financeiro Pro!**\n\nControle total das suas contas aqui.",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🤖 **MENU PRINCIPAL**", reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

# ================= 1. FLUXO DE REGISTRO (BOTÕES) =================

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
        
        # Carrega categorias
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
    
    if data == "new_cat":
        await query.edit_message_text("✍️ **Digite o nome da nova categoria:**")
        return NEW_CAT_NAME
    
    cat = data.replace("cat_", "")
    context.user_data["temp_cat"] = cat
    
    # Sugestões de descrição
    sugestoes = ["Uber", "iFood", "Mercado", "Aluguel", "Pix", "Cartão", "Lanche"]
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

async def reg_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Pode vir de botão (callback) ou texto
    if update.callback_query:
        query = update.callback_query; await query.answer()
        desc = query.data.replace("desc_", "")
        reply_func = query.edit_message_text
    else:
        desc = update.message.text
        reply_func = update.message.reply_text

    # Salva
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

# ================= 2. CRIAR CATEGORIA =================
async def new_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.message.text
    tipo = context.user_data["temp_type"]
    
    if nome not in db["categories"][tipo]:
        db["categories"][tipo].append(nome)
        save_db(db)
        
    context.user_data["temp_cat"] = nome
    # Pula direto para descrição
    kb = [[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]
    await update.message.reply_text(f"✅ Categoria **{nome}** criada!\nAgora a descrição:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_DESC

# ================= 3. CENTRAL DE APAGAR =================
async def menu_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("💲 Apagar Últimas Transações", callback_data="del_list_trans")],
        [InlineKeyboardButton("📂 Apagar Categoria", callback_data="del_list_cat")],
        [InlineKeyboardButton("📌 Apagar Item Fixo", callback_data="del_list_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]
    ]
    await query.edit_message_text("🗑️ **O que deseja apagar?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    # Listar Transações
    if data == "del_list_trans":
        if not db["transactions"]: return await query.edit_message_text("Vazio.", reply_markup=get_main_menu())
        kb = []
        for t in reversed(db["transactions"][-5:]): # Últimas 5
            icon = "🔴" if t['type'] == 'gasto' else "🟢"
            kb.append([InlineKeyboardButton(f"❌ {icon} R$ {t['value']} - {t['category']}", callback_data=f"kill_id_{t['id']}")])
        kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])
        await query.edit_message_text("👇 Clique para deletar:", reply_markup=InlineKeyboardMarkup(kb))
        
    # Executar Delete Transação
    elif data.startswith("kill_id_"):
        tid = data.replace("kill_id_", "")
        db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
        save_db(db)
        await query.edit_message_text("✅ Apagado!", reply_markup=get_main_menu())

    # Listar Categorias
    elif data == "del_list_cat":
        kb = []
        for tipo in ["gasto", "ganho"]:
            for c in db["categories"][tipo]:
                kb.append([InlineKeyboardButton(f"❌ {c} ({tipo})", callback_data=f"kill_cat_{tipo}_{c}")])
        kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])
        await query.edit_message_text("📂 Escolha a Categoria para apagar:", reply_markup=InlineKeyboardMarkup(kb))

    # Executar Delete Categoria
    elif data.startswith("kill_cat_"):
        parts = data.split("_")
        tipo, nome = parts[2], parts[3]
        if nome in db["categories"][tipo]:
            db["categories"][tipo].remove(nome)
            save_db(db)
        await query.edit_message_text(f"✅ Categoria {nome} apagada.", reply_markup=get_main_menu())

    # Listar Fixos
    elif data == "del_list_fixed":
        if not db["fixed_items"]: return await query.edit_message_text("Sem fixos.", reply_markup=get_main_menu())
        kb = []
        for i, item in enumerate(db["fixed_items"]):
            kb.append([InlineKeyboardButton(f"❌ {item['name']} (R$ {item['value']})", callback_data=f"kill_fix_{i}")])
        kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])
        await query.edit_message_text("📌 Clique para apagar Fixo:", reply_markup=InlineKeyboardMarkup(kb))

    # Executar Delete Fixo
    elif data.startswith("kill_fix_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(db["fixed_items"]):
            del db["fixed_items"][idx]
            save_db(db)
        await query.edit_message_text("✅ Fixo apagado.", reply_markup=get_main_menu())

# ================= 4. RELATÓRIOS E FIXOS =================
async def menu_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Novo Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]]
    
    text = "📌 **ITENS FIXOS E SALÁRIOS**\n\n"
    if not db["fixed_items"]: text += "_Nenhum cadastrado._"
    else:
        for f in db["fixed_items"]:
            icon = "🔴" if f['type'] == 'gasto' else "🟢"
            text += f"{icon} {f['name']}: R$ {f['value']:.2f}\n"
            
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite o fixo assim:\n`Tipo Nome Valor`\n\nEx: `ganho Salário 3000`\nEx: `gasto Internet 100`", reply_markup=get_cancel_btn(), parse_mode="Markdown")
    return ADD_FIXED

async def add_fixed_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        parts = text.split(" ")
        tipo = parts[0].lower()
        val = float(parts[-1].replace(",", "."))
        nome = " ".join(parts[1:-1])
        if tipo not in ["gasto", "ganho"]: raise ValueError
        
        db["fixed_items"].append({"type": tipo, "name": nome, "value": val})
        save_db(db)
        await update.message.reply_text("✅ Fixo salvo!", reply_markup=get_main_menu())
    except:
        await update.message.reply_text("❌ Erro. Use: `ganho Salário 2000`")
    return ConversationHandler.END

async def report_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    text = "🕵️ **ANÁLISE DETALHADA**\n\n"
    
    # Fixos
    if db["fixed_items"]:
        text += "📌 **Fixos:**\n"
        for f in db["fixed_items"]:
            text += f"   • {f['name']}: R$ {f['value']:.2f}\n"
        text += "----------------\n"
            
    # Variáveis
    if db["transactions"]:
        text += "📝 **Transações Recentes:**\n"
        for t in reversed(db["transactions"][-15:]):
            icon = "🔴" if t['type'] == 'gasto' else "🟢"
            text += f"{icon} **{t['category']}** | {t['description']}\n   R$ {t['value']:.2f} ({t['date']})\n\n"
    else:
        text += "_Sem transações._"
        
    await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

async def report_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    
    # Cálculos
    var_ganho = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    var_gasto = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    fix_ganho = sum(i['value'] for i in db["fixed_items"] if i['type'] == 'ganho')
    fix_gasto = sum(i['value'] for i in db["fixed_items"] if i['type'] == 'gasto')
    
    total_in = var_ganho + fix_ganho
    total_out = var_gasto + fix_gasto
    saldo = total_in - total_out
    
    msg = (f"📊 **RELATÓRIO FINANCEIRO**\n\n"
           f"💰 **Entradas:** R$ {total_in:.2f}\n"
           f"   _(Fixos: {fix_ganho} | Variável: {var_ganho})_\n\n"
           f"💸 **Saídas:** R$ {total_out:.2f}\n"
           f"   _(Fixos: {fix_gasto} | Variável: {var_gasto})_\n"
           f"────────────────\n"
           f"📈 **SALDO:** R$ {saldo:.2f}")
    
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# ================= 5. METAS =================
async def menu_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    text = "🎯 **METAS MENSAIS**\n\n"
    
    for g in db["goals"]:
        gasto = sum(t['value'] for t in db["transactions"] if t['category'] == g['category'] and t['type'] == 'gasto')
        pct = int((gasto / g['limit']) * 100) if g['limit'] > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - (pct // 10))
        text += f"📂 {g['category']}: {bar} {pct}%\n   R$ {gasto:.0f} / R$ {g['limit']:.0f}\n\n"
        
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite a meta: `Categoria Valor`\nEx: `Lazer 500`", reply_markup=get_cancel_btn(), parse_mode="Markdown")
    return ADD_GOAL

async def add_goal_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cat, val = update.message.text.rsplit(" ", 1)
        db["goals"].append({"category": cat, "limit": float(val)})
        save_db(db)
        await update.message.reply_text("🎯 Meta definida!", reply_markup=get_main_menu())
    except:
        await update.message.reply_text("❌ Erro. Use: `Mercado 800`")
    return ConversationHandler.END

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await update.effective_message.reply_document(open(DB_FILE, "rb"), caption="📦 Seu Backup")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END

# ================= SERVER WEB (ANTI-CRASH) =================
app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "BOT ON"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# ================= MAIN =================
if __name__ == "__main__":
    # Inicia o servidor Web em segundo plano para o Render não reclamar
    threading.Thread(target=run_web, daemon=True).start()
    
    if not TOKEN:
        print("Erro: Sem Token.")
        sys.exit()

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Conversa de Registro
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
    
    # Conversa de Fixos e Metas
    conv_fixed = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")],
        states={ADD_FIXED: [MessageHandler(filters.TEXT, add_fixed_save)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    
    conv_goals = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_goal_start, pattern="^add_goal_start$")],
        states={ADD_GOAL: [MessageHandler(filters.TEXT, add_goal_save)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_reg)
    app.add_handler(conv_fixed)
    app.add_handler(conv_goals)
    
    # Menus e Ações Diretas
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(report_quick, pattern="^report_quick$"))
    app.add_handler(CallbackQueryHandler(report_full, pattern="^report_full$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_handler, pattern="^(del_list_|kill_)"))
    app.add_handler(CallbackQueryHandler(backup, pattern="^backup$"))
    
    print("Bot Iniciado...")
    app.run_polling()