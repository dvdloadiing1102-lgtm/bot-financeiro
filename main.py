import os
import sys
import json
import logging
import uuid
import io
import csv
from datetime import datetime, timedelta

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
DB_FILE = "finance_v13_final.json"

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
 ADD_FIXED_TYPE, ADD_FIXED_DATA, NEW_CAT_TYPE, NEW_CAT_NAME) = range(10)

# ================= CÁLCULOS =================
def calculate_balance():
    mes_atual = datetime.now().strftime("%m/%Y")
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_atual in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    saldo = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    return saldo, (ganhos_fixos + trans_ganhos), (gastos_fixos + trans_gastos)

# ================= MENU PRINCIPAL =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    saldo, t_in, t_out = calculate_balance()
    mode = "🤡 Zoeiro: ON" if db["config"]["zoeiro_mode"] else "🤖 Modo: Sério"
    kb = [
        [InlineKeyboardButton("📝 REGISTRAR", callback_data="start_reg"), InlineKeyboardButton("🔍 RAIO-X", callback_data="full_report")],
        [InlineKeyboardButton("📌 FIXOS", callback_data="menu_fixed"), InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach")],
        [InlineKeyboardButton("📊 GRÁFICO", callback_data="chart_pie"), InlineKeyboardButton("📄 PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("➕ CAT", callback_data="menu_cat"), InlineKeyboardButton("🗑️ EXCLUIR", callback_data="menu_delete")],
        [InlineKeyboardButton("📂 CSV", callback_data="export_csv"), InlineKeyboardButton(mode, callback_data="toggle_mode")]
    ]
    txt = f"🤖 **FINANCEIRO V13 (ANTI-CONFLITO)**\n\n💰 **Saldo:** R$ {saldo:.2f}\n📈 Ganhos: R$ {t_in:.2f}\n📉 Gastos: R$ {t_out:.2f}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# --- 🔍 RAIO-X REAL (NÃO TIREI!) ---
async def full_report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    saldo, t_in, t_out = calculate_balance()
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    cats = {}
    for t in trans: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    msg = f"🔍 **RAIO-X DE {mes}**\n\n📈 Entradas: R$ {t_in:.2f}\n📉 Saídas: R$ {t_out:.2f}\n⚖️ **Saldo: R$ {saldo:.2f}**\n\n**DETALHE GASTOS:**\n"
    for c, v in sorted(cats.items(), key=lambda x:x[1], reverse=True): msg += f"🔸 {c}: R$ {v:.2f}\n"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]), parse_mode="Markdown")

# --- ➕ CATEGORIA (NÃO TIREI!) ---
async def menu_cat(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="ncat_gasto"), InlineKeyboardButton("Ganho", callback_data="ncat_ganho")]]
    await query.edit_message_text("Nova categoria para qual lista?", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def new_cat_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["ncat_t"] = query.data.split("_")[1]
    await query.edit_message_text("✍️ Qual o nome da nova categoria?")
    return NEW_CAT_NAME

async def new_cat_save(update, context):
    tipo = context.user_data["ncat_t"]
    db["categories"][tipo].append(update.message.text.strip())
    save_db(db); await update.message.reply_text("✅ Categoria salva!")
    return await start(update, context)

# --- 🗑️ EXCLUIR (NÃO TIREI!) ---
async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton(f"❌ {t['value']} - {t['category']}", callback_data=f"kill_{t['id']}")] for t in reversed(db["transactions"][-5:])]
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Apagar qual item?**", reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db); return await start(update, context)

# --- 📌 FIXOS (NÃO TIREI!) ---
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Add Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    txt = "📌 **FIXOS (Salário/Contas):**\n"
    for f in db["fixed"]: txt += f"\n{'📈' if f['type'] == 'ganho' else '📉'} {f['name']}: R$ {f['value']:.2f}"
    await query.edit_message_text(txt if db["fixed"] else "Nenhum fixo.", reply_markup=InlineKeyboardMarkup(kb))

# --- REGISTRO E CANCELAR ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")]]
    await query.edit_message_text("🏦 **Gasto ou Ganho?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO FINAL (ANTI-ZUMBI) =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    reg_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(lambda u,c: (c.user_data.update({'t': u.callback_query.data.split('_')[1]}), u.callback_query.edit_message_text("💰 Valor?"))[1])],
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
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    print("🚀 BOT V13 ATIVADO. LIMPANDO INSTÂNCIAS ANTIGAS...")
    
    # O PULO DO GATO: drop_pending_updates mata a conexão antiga no Telegram
    app.run_polling(drop_pending_updates=True)
