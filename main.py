import os
import sys
import subprocess
import json
import logging
import uuid
from datetime import datetime

# --- AUTO-INSTALAÇÃO ---
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("⚠️ Instalando dependências...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
DB_FILE = "finance_v2.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Casa", "Lazer"]
        },
        "fixed_items": [], # Salários fixos ou contas fixas
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
def get_main_menu():
    kb = [
        [InlineKeyboardButton("📝 Registrar Novo", callback_data="reg_start")],
        [InlineKeyboardButton("📊 Relatório Rápido", callback_data="report_quick"),
         InlineKeyboardButton("🕵️ Análise Detalhada", callback_data="report_full")],
        [InlineKeyboardButton("📌 Fixos/Salários", callback_data="menu_fixed"),
         InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("🗑️ Gerenciar/Apagar", callback_data="menu_delete")]
    ]
    return InlineKeyboardMarkup(kb)

def get_cancel_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="main_menu")]])

# ================= FLUXO DE REGISTRO (BOTÕES) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🤖 **FINANCEIRO PRO**\nSelecione uma opção:", reply_markup=get_main_menu(), parse_mode="Markdown")

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🤖 **MENU PRINCIPAL**", reply_markup=get_main_menu(), parse_mode="Markdown")

# 1. Escolher Tipo
async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("📉 É um GASTO", callback_data="type_gasto")],
        [InlineKeyboardButton("📈 É um GANHO", callback_data="type_ganho")],
        [InlineKeyboardButton("⬅️ Cancelar", callback_data="main_menu")]
    ]
    await query.edit_message_text("Passo 1/4: **O que você vai registrar?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# 2. Pedir Valor
async def reg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    tipo = query.data.split("_")[1]
    context.user_data["temp_type"] = tipo
    context.user_data["step"] = "awaiting_value"
    
    emoji = "💸" if tipo == "gasto" else "💰"
    await query.edit_message_text(f"{emoji} Passo 2/4: **Qual o valor?**\n\nDigite apenas números (ex: `25.50` ou `100`)", reply_markup=get_cancel_btn(), parse_mode="Markdown")

# 3. Escolher Categoria
async def reg_category_prompt(update, context, value_str):
    try:
        value = float(value_str.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite novamente:")
        return

    context.user_data["temp_value"] = value
    context.user_data["step"] = "selecting_category"
    
    tipo = context.user_data["temp_type"]
    cats = db["categories"].get(tipo, [])
    
    kb = []
    # Cria botões, 2 por linha
    row = []
    for c in cats:
        row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    kb.append([InlineKeyboardButton("➕ Criar Nova Categoria", callback_data="new_cat_flow")])
    kb.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="main_menu")])
    
    await update.message.reply_text(f"Passo 3/4: **Escolha a Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# 4. Escolher/Digitar Descrição
async def reg_desc_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cat = query.data.replace("cat_", "")
    context.user_data["temp_cat"] = cat
    context.user_data["step"] = "awaiting_desc"
    
    # Sugestões rápidas baseadas na categoria
    suggestions = ["Uber", "iFood", "Mercado", "Aluguel", "Pix", "Cartão"]
    kb = []
    row = []
    for s in suggestions:
        row.append(InlineKeyboardButton(s, callback_data=f"desc_{s}"))
        if len(row) == 3: kb.append(row); row = []
    if row: kb.append(row)
    
    kb.append([InlineKeyboardButton("⏩ Pular Descrição", callback_data="desc_Sem Descrição")])
    
    await query.edit_message_text(
        f"Passo 4/4: **Descrição para '{cat}'**\n\nEscolha uma rápida ou DIGITE o nome (ex: Padaria do João):",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )

# 5. Salvar Final
async def finish_registration(update, context, desc_text=None):
    if update.callback_query:
        query = update.callback_query
        desc = query.data.replace("desc_", "")
        func_reply = query.edit_message_text
    else:
        desc = desc_text
        func_reply = update.message.reply_text

    # Dados finais
    t_type = context.user_data["temp_type"]
    val = context.user_data["temp_value"]
    cat = context.user_data["temp_cat"]
    
    # Salva no DB com ID único
    item = {
        "id": str(uuid.uuid4())[:8],
        "type": t_type,
        "value": val,
        "category": cat,
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    db["transactions"].append(item)
    save_db(db)
    
    msg = f"✅ **Registrado com Sucesso!**\n\n{'➖' if t_type=='gasto' else '➕'} R$ {val:.2f}\n📂 {cat}\n📝 {desc}"
    await func_reply(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    context.user_data.clear()

# ================= SISTEMA DE FIXOS/SALÁRIO =================
async def menu_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("➕ Adicionar Fixo", callback_data="add_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]
    ]
    
    text = "📌 **ITENS FIXOS (Mensais)**\n\n"
    if not db["fixed_items"]: text += "_Nenhum item fixo cadastrado._"
    else:
        for item in db["fixed_items"]:
            sinal = "-" if item['type'] == 'gasto' else "+"
            text += f"• {item['name']}: {sinal}R$ {item['value']:.2f}\n"
            
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["step"] = "adding_fixed"
    await query.edit_message_text("Digite o fixo no formato:\n`Tipo Nome Valor`\n\nExemplos:\n`ganho Salário 3000`\n`gasto Internet 100`", reply_markup=get_cancel_btn(), parse_mode="Markdown")

# ================= RELATÓRIOS E ANÁLISE =================
async def report_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    
    if not db["transactions"]:
        await query.edit_message_text("📭 Nenhuma transação registrada.", reply_markup=get_main_menu())
        return

    text = "🕵️ **ANÁLISE DETALHADA**\n\n"
    
    # Lista invertida (mais recente primeiro)
    for t in reversed(db["transactions"]):
        icon = "🔴" if t['type'] == 'gasto' else "🟢"
        date_short = t['date'].split(" ")[0]
        text += f"{icon} **{t['category']}**\n"
        text += f"   └ 📝 {t['description']} | R$ {t['value']:.2f}\n"
        text += f"   └ 📅 {date_short} (ID: `{t['id']}`)\n\n"
        
    # Divide mensagem se for muito grande
    if len(text) > 4000: text = text[:4000] + "\n...(lista cortada)..."
    
    await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

async def report_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    
    # 1. Soma Transações Variáveis
    var_ganho = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    var_gasto = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    
    # 2. Soma Fixos
    fix_ganho = sum(i['value'] for i in db["fixed_items"] if i['type'] == 'ganho')
    fix_gasto = sum(i['value'] for i in db["fixed_items"] if i['type'] == 'gasto')
    
    total_entrada = var_ganho + fix_ganho
    total_saida = var_gasto + fix_gasto
    saldo = total_entrada - total_saida
    
    text = f"📊 **RELATÓRIO GERAL**\n\n"
    text += f"💰 **Entradas:** R$ {total_entrada:.2f}\n"
    text += f"   _(Variável: {var_ganho} | Fixo: {fix_ganho})_\n\n"
    text += f"💸 **Saídas:** R$ {total_saida:.2f}\n"
    text += f"   _(Variável: {var_gasto} | Fixo: {fix_gasto})_\n"
    text += "──────────────────\n"
    text += f"📈 **SALDO FINAL: R$ {saldo:.2f}**"
    
    await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

# ================= METAS (VISUAL MELHORADO) =================
async def menu_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    
    text = "🎯 **SUAS METAS**\n\n"
    if not db["goals"]: text += "_Nenhuma meta definida._"
    
    for g in db["goals"]:
        # Calcula quanto gastou nessa categoria no mês atual
        gasto_atual = sum(t['value'] for t in db["transactions"] 
                          if t['category'] == g['category'] and t['type'] == 'gasto')
        
        pct = min(100, int((gasto_atual / g['limit']) * 100))
        bar = "█" * (pct // 10) + "░" * (10 - (pct // 10))
        
        text += f"📂 **{g['category']}**\n"
        text += f"   └ {bar} {pct}%\n"
        text += f"   └ R$ {gasto_atual:.0f} de R$ {g['limit']:.0f}\n\n"
        
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal")], [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["step"] = "adding_goal"
    await query.edit_message_text("Defina a meta:\n`Categoria Valor`\nEx: `Lazer 500`", reply_markup=get_cancel_btn(), parse_mode="Markdown")

# ================= DELETAR ITENS (GRANULAR) =================
async def menu_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("💲 Deletar uma Transação", callback_data="del_trans")],
        [InlineKeyboardButton("📂 Deletar Categoria", callback_data="del_cat")],
        [InlineKeyboardButton("📌 Deletar Item Fixo", callback_data="del_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]
    ]
    await query.edit_message_text("🗑️ **GERENCIAR E APAGAR**\nO que você deseja remover?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def del_trans_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if not db["transactions"]:
        await query.edit_message_text("Sem transações.", reply_markup=get_main_menu())
        return
    
    kb = []
    # Mostra as últimas 5
    for t in db["transactions"][-5:]:
        btn_text = f"❌ {t['category']} (R$ {t['value']})"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"confirm_del_{t['id']}")])
    
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])
    await query.edit_message_text("👇 Clique para apagar permanentemente:", reply_markup=InlineKeyboardMarkup(kb))

async def del_cat_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = []
    # Lista categorias de gasto e ganho
    for tipo in ["gasto", "ganho"]:
        for c in db["categories"][tipo]:
            kb.append([InlineKeyboardButton(f"❌ {c} ({tipo})", callback_data=f"kill_cat_{tipo}_{c}")])
            
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])
    await query.edit_message_text("⚠️ **Apagar Categoria**\nIsso não apaga as transações antigas, apenas a opção de criar novas.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def execute_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    if data.startswith("confirm_del_"):
        tid = data.replace("confirm_del_", "")
        db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
        save_db(db)
        await query.edit_message_text("✅ Transação apagada!", reply_markup=get_main_menu())
        
    elif data.startswith("kill_cat_"):
        parts = data.split("_") # kill, cat, tipo, nome
        tipo = parts[2]
        nome = parts[3]
        if nome in db["categories"][tipo]:
            db["categories"][tipo].remove(nome)
            save_db(db)
        await query.edit_message_text(f"✅ Categoria {nome} removida.", reply_markup=get_main_menu())

# ================= PROCESSADOR DE TEXTO (INPUTS) =================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    text = update.message.text
    
    # Fluxo de Registro: Valor
    if step == "awaiting_value":
        await reg_category_prompt(update, context, text)
        return

    # Fluxo de Registro: Descrição Manual
    if step == "awaiting_desc":
        await finish_registration(update, context, desc_text=text)
        return

    # Fluxo: Adicionar Fixo
    if step == "adding_fixed":
        try:
            tipo, nome, val = text.split(" ")
            tipo = tipo.lower()
            if tipo not in ["ganho", "gasto"]: raise ValueError
            db["fixed_items"].append({"type": tipo, "name": nome, "value": float(val.replace(",", "."))})
            save_db(db)
            await update.message.reply_text("✅ Item fixo salvo!", reply_markup=get_main_menu())
        except:
            await update.message.reply_text("❌ Erro. Use: `ganho Salário 2000`")
        context.user_data.clear()
        return

    # Fluxo: Nova Categoria
    if step == "new_cat_name":
        # Assume que o user veio de um fluxo, precisamos saber se é gasto ou ganho
        # Como o fluxo de registro salva 'temp_type', vamos usar ele
        tipo = context.user_data.get("temp_type", "gasto") # Default gasto se perder contexto
        if text not in db["categories"][tipo]:
            db["categories"][tipo].append(text)
            save_db(db)
            # Volta para o fluxo de registro
            context.user_data["temp_cat"] = text
            # Pula para descrição
            kb = [[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]
            await update.message.reply_text(f"✅ Categoria **{text}** criada! Agora a descrição:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            context.user_data["step"] = "awaiting_desc"
        else:
            await update.message.reply_text("Categoria já existe.")
        return

    # Fluxo: Meta
    if step == "adding_goal":
        try:
            cat, val = text.rsplit(" ", 1)
            db["goals"].append({"category": cat, "limit": float(val)})
            save_db(db)
            await update.message.reply_text("🎯 Meta definida!", reply_markup=get_main_menu())
        except:
            await update.message.reply_text("Erro. Use: `Lazer 500`")
        context.user_data.clear()
        return

async def new_cat_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["step"] = "new_cat_name"
    await query.edit_message_text("✍️ Digite o nome da nova categoria:", parse_mode="Markdown")

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Menus
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    
    # Registro
    app.add_handler(CallbackQueryHandler(reg_start, pattern="^reg_start$"))
    app.add_handler(CallbackQueryHandler(reg_type, pattern="^type_"))
    app.add_handler(CallbackQueryHandler(reg_desc_prompt, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(finish_registration, pattern="^desc_"))
    app.add_handler(CallbackQueryHandler(new_cat_flow, pattern="^new_cat_flow$"))
    
    # Relatórios e Fixos
    app.add_handler(CallbackQueryHandler(report_quick, pattern="^report_quick$"))
    app.add_handler(CallbackQueryHandler(report_full, pattern="^report_full$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(add_fixed_prompt, pattern="^add_fixed$"))
    
    # Metas e Delete
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(add_goal_prompt, pattern="^add_goal$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(del_trans_list, pattern="^del_trans$"))
    app.add_handler(CallbackQueryHandler(del_cat_list, pattern="^del_cat$"))
    app.add_handler(CallbackQueryHandler(execute_deletion, pattern="^(confirm_del_|kill_cat_)"))
    
    # Texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))
    
    print("Bot Iniciado...")
    app.run_polling()
