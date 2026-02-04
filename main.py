import os
import sys
import json
import logging
import uuid
import io
import csv
import random
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# --- AUTO-INSTALAÇÃO ---
try:
    import google.generativeai as genai
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "matplotlib", "reportlab", "google-generativeai"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
GEMINI_KEY = "AIzaSyAV-9NqZ60BNapV4-ADQ1gSRffRkpeu4-w" 
DB_FILE = "finance_v12_definitivo.json"

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa"]}, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter"],
        "fixed": [], "goals": [], "config": {"zoeiro_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= ESTADOS =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_PARCELAS, REG_CAT, REG_DESC, 
 ADD_FIXED_TYPE, ADD_FIXED_DATA, NEW_CAT_TYPE, NEW_CAT_NAME, ADD_GOAL) = range(11)

# ================= CÁLCULOS =================
def calculate_balance():
    mes_atual = datetime.now().strftime("%m/%Y")
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_atual in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    saldo = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    return saldo, (ganhos_fixos + trans_ganhos), (gastos_fixos + trans_gastos)

# ================= MENU =================
async def start(update, context):
    context.user_data.clear()
    saldo, t_in, t_out = calculate_balance()
    mode = "🤡 Zoeiro: ON" if db["config"]["zoeiro_mode"] else "🤖 Modo: Sério"
    kb = [
        [InlineKeyboardButton("📝 REGISTRAR", callback_data="start_reg"), InlineKeyboardButton("🔍 RAIO-X", callback_data="full_report")],
        [InlineKeyboardButton("📌 FIXOS", callback_data="menu_fixed"), InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach")],
        [InlineKeyboardButton("📊 GRÁFICO", callback_data="chart_pie"), InlineKeyboardButton("📄 PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("🆚 Mês x Mês", callback_data="compare_months"), InlineKeyboardButton("📂 CSV", callback_data="export_csv")],
        [InlineKeyboardButton("➕ CAT", callback_data="menu_cat"), InlineKeyboardButton("🎯 METAS", callback_data="menu_goals")],
        [InlineKeyboardButton(mode, callback_data="toggle_mode"), InlineKeyboardButton("🗑️ EXCLUIR", callback_data="menu_delete")]
    ]
    txt = f"🤖 **FINANCEIRO V12.0**\n\n💰 **Saldo Real:** R$ {saldo:.2f}\n📈 Entradas: R$ {t_in:.2f}\n📉 Saídas: R$ {t_out:.2f}"
    msg = update.callback_query.message if update.callback_query else update.message
    await (msg.edit_text if update.callback_query else msg.reply_text)(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# --- 🔍 RAIO-X REAL ---
async def full_report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    saldo, t_in, t_out = calculate_balance()
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    cats = {}
    for t in trans: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    msg = f"🔍 **RAIO-X DETALHADO ({mes})**\n\n📈 Entradas Totais: R$ {t_in:.2f}\n📉 Saídas Totais: R$ {t_out:.2f}\n⚖️ **Saldo Real: R$ {saldo:.2f}**\n\n**DETALHE GASTOS:**\n"
    for c, v in sorted(cats.items(), key=lambda x:x[1], reverse=True): msg += f"🔸 {c}: R$ {v:.2f}\n"
    await query.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]), parse_mode="Markdown")

# --- ➕ ADICIONAR CATEGORIA ---
async def menu_cat(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="ncat_gasto"), InlineKeyboardButton("Ganho", callback_data="ncat_ganho")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    await query.edit_text("Adicionar categoria em qual lista?", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def new_cat_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["ncat_t"] = query.data.split("_")[1]
    await query.edit_text("✍️ Digite o nome da nova categoria:")
    return NEW_CAT_NAME

async def new_cat_save(update, context):
    db["categories"][context.user_data["ncat_t"]].append(update.message.text.strip())
    save_db(db)
    await update.message.reply_text("✅ Categoria adicionada!")
    return await start(update, context)

# --- 📌 GESTÃO DE FIXOS ---
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Add Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    txt = "📌 **FIXOS (Salário e Contas):**\n"
    for f in db["fixed"]: txt += f"\n{'📈' if f['type'] == 'ganho' else '📉'} {f['name']}: R$ {f['value']:.2f}"
    await query.edit_text(txt if db["fixed"] else "Nenhum fixo.", reply_markup=InlineKeyboardMarkup(kb))

async def add_fixed_start(update, context):
    kb = [[InlineKeyboardButton("📈 GANHO (Salário)", callback_data="fix_ganho")], [InlineKeyboardButton("📉 GASTO (Conta)", callback_data="fix_gasto")]]
    await update.callback_query.edit_message_text("O que deseja fixar?", reply_markup=InlineKeyboardMarkup(kb))
    return ADD_FIXED_TYPE

async def add_fixed_save(update, context):
    p = update.message.text.rsplit(" ", 1)
    db["fixed"].append({"name": p[0], "value": float(p[1]), "type": context.user_data["fix_type"]})
    save_db(db); return await start(update, context)

# --- 📝 REGISTRO COMPLETO ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")]]
    await query.edit_text("🏦 **Gasto ou Ganho?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_value(update, context):
    context.user_data["temp_type"] = update.callback_query.data.split("_")[1]
    await update.callback_query.edit_text("💰 **Valor?**")
    return REG_VALUE

async def reg_wallet(update, context):
    context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
    kb = [[InlineKeyboardButton(w, callback_data=f"wallet_{w}")] for w in db["wallets"]]
    await update.message.reply_text("💳 **Carteira?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_WALLET

async def reg_cat_ask(update, context):
    context.user_data["temp_wallet"] = update.callback_query.data.replace("wallet_", "")
    cats = db["categories"][context.user_data["temp_type"]]
    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await update.callback_query.edit_text("📂 **Categoria:**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_CAT

async def reg_desc_ask(update, context):
    context.user_data["temp_cat"] = update.callback_query.data.replace("cat_", "")
    await update.callback_query.edit_text("✍️ **Descrição (Uber, etc):**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]))
    return REG_DESC

async def reg_finish(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    db["transactions"].append({"id": str(uuid.uuid4())[:8], "type": context.user_data["temp_type"], "value": context.user_data["temp_value"], "category": context.user_data["temp_cat"], "date": datetime.now().strftime("%d/%m/%Y %H:%M"), "description": desc})
    save_db(db); return await start(update, context)

async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    reg_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_value)],
            REG_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_wallet)],
            REG_WALLET: [CallbackQueryHandler(reg_cat_ask)],
            REG_CAT: [CallbackQueryHandler(reg_desc_ask)],
            REG_DESC: [CallbackQueryHandler(reg_finish), MessageHandler(filters.TEXT & ~filters.COMMAND, reg_finish)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    cat_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_cat, pattern="^menu_cat$")],
        states={
            NEW_CAT_TYPE: [CallbackQueryHandler(new_cat_type)],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_cat_save)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start)); app.add_handler(reg_h); app.add_handler(cat_h)
    app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    app.run_polling()
