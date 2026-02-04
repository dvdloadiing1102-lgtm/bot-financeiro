import os
import json
import logging
import uuid
import io
import csv
from datetime import datetime, timedelta

# Importações das bibliotecas (certifique-se de que estão no Build Command do Render)
import google.generativeai as genai
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
GEMINI_KEY = "AIzaSyAV-9NqZ60BNapV4-ADQ1gSRffRkpeu4-w" 
DB_FILE = "finance_v16_database.json"

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde"]}, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA"],
        "fixed": [], "config": {"zoeiro_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= ESTADOS DO FLUXO =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_CAT, REG_DESC, 
 NEW_CAT_TYPE, NEW_CAT_NAME, ADD_FIX_TYPE, ADD_FIX_DATA) = range(9)

# ================= CÁLCULOS TOTAIS =================
def calculate_balance():
    mes_atual = datetime.now().strftime("%m/%Y")
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_atual in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    saldo = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    return saldo, (ganhos_fixos + trans_ganhos), (gastos_fixos + trans_gastos)

# ================= MENU PRINCIPAL =================
async def start(update, context):
    context.user_data.clear()
    saldo, t_in, t_out = calculate_balance()
    mode = "🤡 Zoeiro: ON" if db["config"]["zoeiro_mode"] else "🤖 Modo: Sério"
    
    kb = [
        [InlineKeyboardButton("📝 REGISTRAR", callback_data="start_reg"), InlineKeyboardButton("🔍 RAIO-X", callback_data="full_report")],
        [InlineKeyboardButton("📌 FIXOS", callback_data="menu_fixed"), InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach")],
        [InlineKeyboardButton("📊 GRÁFICO", callback_data="chart_pie"), InlineKeyboardButton("➕ CAT", callback_data="menu_cat")],
        [InlineKeyboardButton("🗑️ EXCLUIR", callback_data="menu_delete"), InlineKeyboardButton(mode, callback_data="toggle_mode")],
        [InlineKeyboardButton("📄 PDF", callback_data="export_pdf"), InlineKeyboardButton("📂 CSV", callback_data="export_csv")]
    ]
    
    txt = f"🤖 **FINANCEIRO V16.0**\n\n💰 **Saldo Real:** R$ {saldo:.2f}\n📈 Ganhos: R$ {t_in:.2f}\n📉 Gastos: R$ {t_out:.2f}"
    
    msg = update.callback_query.message if update.callback_query else update.message
    await (msg.edit_text if update.callback_query else msg.reply_text)(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= FUNÇÕES DO RAIO-X =================
async def full_report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    saldo, t_in, t_out = calculate_balance()
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    
    cats = {}
    for t in trans: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    msg = f"🔍 **RAIO-X DE {mes}**\n\n📈 Entradas Totais: R$ {t_in:.2f}\n📉 Saídas Totais: R$ {t_out:.2f}\n⚖️ **Saldo: R$ {saldo:.2f}**\n\n**GASTOS POR CATEGORIA:**\n"
    for c, v in sorted(cats.items(), key=lambda x:x[1], reverse=True):
        msg += f"🔸 {c}: R$ {v:.2f}\n"
    
    await query.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]), parse_mode="Markdown")

# ================= FUNÇÕES DE CATEGORIA =================
async def menu_cat(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="ncat_gasto"), InlineKeyboardButton("Ganho", callback_data="ncat_ganho")], [InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")]]
    await query.edit_text("Adicionar categoria em qual lista?", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def new_cat_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["ncat_t"] = query.data.split("_")[1]
    await query.edit_text("✍️ Digite o nome da nova categoria:")
    return NEW_CAT_NAME

async def new_cat_save(update, context):
    tipo = context.user_data["ncat_t"]
    db["categories"][tipo].append(update.message.text.strip())
    save_db(db); await update.message.reply_text("✅ Categoria adicionada!"); return await start(update, context)

# ================= FUNÇÕES DE EXCLUSÃO =================
async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton(f"❌ {t['value']} - {t['category']}", callback_data=f"kill_{t['id']}")] for t in reversed(db["transactions"][-5:])]
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])
    await query.edit_text("🗑️ **Selecione para apagar:**", reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db); return await start(update, context)

# ================= FLUXO DE REGISTRO PASSO A PASSO =================
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="reg_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="reg_ganho")]]
    await query.edit_text("🏦 **Tipo de registro:**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_text("💰 **Qual o valor?**")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        kb = [[InlineKeyboardButton(w, callback_data=f"wal_{w}")] for w in db["wallets"]]
        await update.message.reply_text("💳 **Qual carteira?**", reply_markup=InlineKeyboardMarkup(kb))
        return REG_WALLET
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_wallet(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_wallet"] = query.data.replace("wal_", "")
    cats = db["categories"][context.user_data["temp_type"]]
    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await query.edit_text("📂 **Qual categoria?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_CAT

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    await query.edit_text("✍️ **Descrição?**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="skip_desc")]]))
    return REG_DESC

async def reg_finish(update, context):
    desc = "Sem descrição" if (update.callback_query and update.callback_query.data == "skip_desc") else update.message.text
    db["transactions"].append({
        "id": str(uuid.uuid4())[:8], "type": context.user_data["temp_type"], "value": context.user_data["temp_value"],
        "category": context.user_data["temp_cat"], "wallet": context.user_data["temp_wallet"],
        "description": desc, "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_db(db); return await start(update, context)

# ================= FUNÇÃO CANCELAR =================
async def cancel(update, context):
    await start(update, context)
    return ConversationHandler.END

# ================= MODO ZOMEIRO E IA =================
async def toggle_mode(update, context):
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db); return await start(update, context)

async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_text("🧠 **Gemini analisando...**")
    saldo, t_in, t_out = calculate_balance()
    prompt = "És um consultor financeiro. " + ("Sê sarcástico e goza com o utilizador." if db["config"]["zoeiro_mode"] else "Dá um conselho sério.")
    try:
        resp = model_ai.generate_content(f"{prompt} Saldo: {saldo}, Entradas: {t_in}, Saídas: {t_out}")
        await query.edit_text(f"🧠 **COACH IA:**\n\n{resp.text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
    except: await query.edit_text("❌ Erro na IA.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))

# ================= EXECUÇÃO FINAL =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handler de Registro
    reg_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type)],
            REG_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_value)],
            REG_WALLET: [CallbackQueryHandler(reg_wallet)],
            REG_CAT: [CallbackQueryHandler(reg_cat)],
            REG_DESC: [CallbackQueryHandler(reg_finish), MessageHandler(filters.TEXT & ~filters.COMMAND, reg_finish)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    
    # Handler de Categoria
    cat_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_cat, pattern="^menu_cat$")],
        states={
            NEW_CAT_TYPE: [CallbackQueryHandler(new_cat_type)],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_cat_save)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_handler)
    app.add_handler(cat_handler)
    app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
    app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    print("🚀 BOT V16 ONLINE! LIMPANDO CONEXÕES ANTIGAS...")
    app.run_polling(drop_pending_updates=True)
