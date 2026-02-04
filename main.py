import os
import sys
import json
import logging
import uuid
import threading
import io
import csv
import random
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
try:
    import httpx
    import google.generativeai as genai
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx", "matplotlib", "reportlab", "google-generativeai"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
GEMINI_KEY = "AIzaSyAV-9NqZ60BNapV4-ADQ1gSRffRkpeu4-w" 
DB_FILE = "finance_v9_ultimate.json"

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Saúde", "Casa"]}, 
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
 ADD_FIXED_TYPE, ADD_FIXED_DATA, NEW_CAT_TYPE, NEW_CAT_NAME) = range(10)

# ================= FUNÇÕES DE APOIO =================
def calculate_balance():
    mes_atual = datetime.now().strftime("%m/%Y")
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_atual in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    saldo = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    return saldo, (ganhos_fixos + trans_ganhos), (gastos_fixos + trans_gastos)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    saldo, t_in, t_out = calculate_balance()
    mode = "🤡 Zoeiro: ON" if db["config"]["zoeiro_mode"] else "🤖 Modo: Sério"
    emoji = "💰" if saldo >= 0 else "🚨"
    
    kb = [
        [InlineKeyboardButton("📝 REGISTRAR", callback_data="start_reg"), InlineKeyboardButton("🔍 RAIO-X", callback_data="full_report")],
        [InlineKeyboardButton("📌 FIXOS", callback_data="menu_fixed"), InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach")],
        [InlineKeyboardButton("📊 GRÁFICO", callback_data="chart_pie"), InlineKeyboardButton("➕ CAT", callback_data="menu_cat")],
        [InlineKeyboardButton("🆚 Mês x Mês", callback_data="compare_months"), InlineKeyboardButton(mode, callback_data="toggle_mode")],
        [InlineKeyboardButton("📄 PDF", callback_data="export_pdf"), InlineKeyboardButton("📂 CSV", callback_data="export_csv")],
        [InlineKeyboardButton("🗑️ EXCLUIR", callback_data="menu_delete")]
    ]
    
    txt = f"🤖 **FINANCEIRO V9**\n\n{emoji} **Saldo Real:** R$ {saldo:.2f}\n📈 Entradas: R$ {t_in:.2f}\n📉 Saídas: R$ {t_out:.2f}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= HANDLERS DE Categoria / Excluir / Raio-X =================

async def menu_cat(update, context):
    kb = [[InlineKeyboardButton("Gasto", callback_data="ncat_gasto"), InlineKeyboardButton("Ganho", callback_data="ncat_ganho")], [InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")]]
    await update.callback_query.edit_message_text("Criar categoria em qual lista?", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def new_cat_type(update, context):
    context.user_data["ncat_t"] = update.callback_query.data.split("_")[1]
    await update.callback_query.edit_message_text("✍️ Digite o nome da nova categoria:")
    return NEW_CAT_NAME

async def new_cat_save(update, context):
    tipo = context.user_data["ncat_t"]
    db["categories"][tipo].append(update.message.text)
    save_db(db); await update.message.reply_text("✅ Categoria adicionada!"); return await start(update, context)

async def full_report(update, context):
    mes = datetime.now().strftime("%m/%Y")
    trans = [t for t in db["transactions"] if mes in t['date']]
    g_total = sum(t['value'] for t in trans if t['type'] == 'ganho')
    s_total = sum(t['value'] for t in trans if t['type'] == 'gasto')
    saldo, t_in, t_out = calculate_balance()
    
    msg = f"🔍 **RAIO-X DE {mes}**\n\n📈 Entradas Totais: R$ {t_in:.2f}\n📉 Saídas Totais: R$ {t_out:.2f}\n⚖️ Saldo Real: R$ {saldo:.2f}"
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]), parse_mode="Markdown")

async def menu_delete(update, context):
    kb = [[InlineKeyboardButton(f"❌ {t['value']} - {t['category']}", callback_data=f"kill_{t['id']}")] for t in reversed(db["transactions"][-5:])]
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])
    await update.callback_query.edit_message_text("🗑️ **Toque para apagar:**", reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update, context):
    tid = update.callback_query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db); return await start(update, context)

# --- REGRAS DE REGISTRO PASSO A PASSO ---
async def start_reg(update, context):
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")], [InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")]]
    await update.callback_query.edit_message_text("🏦 **Gasto ou Ganho?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    context.user_data["temp_type"] = update.callback_query.data.split("_")[1]
    await update.callback_query.edit_message_text("💰 **Valor?**")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        kb = [[InlineKeyboardButton(w, callback_data=f"wallet_{w}")] for w in db["wallets"]]
        await update.message.reply_text("💳 **Carteira?**", reply_markup=InlineKeyboardMarkup(kb))
        return REG_WALLET
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_wallet(update, context):
    context.user_data["temp_wallet"] = update.callback_query.data.replace("wallet_", "")
    if context.user_data["temp_type"] == "gasto":
        kb = [[InlineKeyboardButton("À Vista", callback_data="parc_1")], [InlineKeyboardButton("12x", callback_data="parc_12")]]
        await update.callback_query.edit_message_text("📅 **Parcelado?**", reply_markup=InlineKeyboardMarkup(kb)); return REG_PARCELAS
    context.user_data["temp_parc"] = 1; return await ask_cat(update, context)

async def ask_cat(update, context):
    cats = db["categories"][context.user_data["temp_type"]]
    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)("📂 **Categoria:**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_CAT

async def reg_finish(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    parc = context.user_data.get("temp_parc", 1)
    val = context.user_data["temp_value"] / parc
    for i in range(parc):
        db["transactions"].append({"id": str(uuid.uuid4())[:8], "type": context.user_data["temp_type"], "value": val, "category": context.user_data.get("temp_cat", "Geral"), "wallet": context.user_data["temp_wallet"], "description": desc, "date": (datetime.now() + timedelta(days=30*i)).strftime("%d/%m/%Y %H:%M")})
    save_db(db); return await start(update, context)

async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO FINAL =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    reg_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type)], 
            REG_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_value)],
            REG_WALLET: [CallbackQueryHandler(reg_wallet)],
            REG_PARCELAS: [CallbackQueryHandler(lambda u,c: (c.user_data.update({"temp_parc": int(u.callback_query.data.split("_")[1])}), ask_cat(u,c))[1])],
            REG_CAT: [CallbackQueryHandler(lambda u,c: (c.user_data.update({"temp_cat": u.callback_query.data.split("_")[1]}), u.callback_query.edit_message_text("✍️ Descrição:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]])))[1])],
            REG_DESC: [CallbackQueryHandler(reg_finish, pattern="^desc_"), MessageHandler(filters.TEXT & ~filters.COMMAND, reg_finish)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    cat_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_cat, pattern="^menu_cat$")],
        states={
            NEW_CAT_TYPE: [CallbackQueryHandler(new_cat_type)],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_cat_save)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_h); app.add_handler(cat_h)
    app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    print("🚀 BOT V9 ULTIMATE RODANDO...")
    app.run_polling()
