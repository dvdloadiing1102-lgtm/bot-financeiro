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
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "google-generativeai"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
GEMINI_KEY = "AIzaSyAV-9NqZ60BNapV4-ADQ1gSRffRkpeu4-w" 
DB_FILE = "finance_v6_9.json"

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra", "Investimento"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Saúde", "Casa"]}, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter"],
        "fixed": [], # Ganhos e Gastos fixos (Salário, Aluguel, etc.)
        "config": {"zoeiro_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= CÁLCULO DE SALDO DINÂMICO =================
def calculate_balance():
    # 1. Base nos Fixos (Salário - Gastos Fixos)
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    
    # 2. Transações do Mês Atual
    mes_atual = datetime.now().strftime("%m/%Y")
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_atual in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    
    saldo_total = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    return saldo_total, ganhos_fixos, gastos_fixos, trans_ganhos, trans_gastos

# ================= INTERFACE =================
def get_main_menu():
    saldo, g_fix, s_fix, g_trans, s_trans = calculate_balance()
    mode_text = "🤡 Mode: ON" if db["config"]["zoeiro_mode"] else "🤖 Mode: OFF"
    
    status_emoji = "💰" if saldo >= 0 else "🚨"
    
    kb = [
        [InlineKeyboardButton("📝 NOVO REGISTRO", callback_data="start_reg")],
        [InlineKeyboardButton("🔍 RAIO-X DETALHADO", callback_data="full_report"), InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach")],
        [InlineKeyboardButton("📌 GESTÃO DE FIXOS", callback_data="menu_fixed")],
        [InlineKeyboardButton("📂 EXPORTAR CSV", callback_data="export_csv"), InlineKeyboardButton("➕ CATEGORIA", callback_data="menu_cat")],
        [InlineKeyboardButton(f"{mode_text}", callback_data="toggle_mode")]
    ]
    
    texto_menu = (
        f"🤖 **FINANCEIRO V6.9**\n\n"
        f"{status_emoji} **Saldo Atual:** R$ {saldo:.2f}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 Entradas: R$ {g_fix + g_trans:.2f}\n"
        f"📉 Saídas: R$ {s_fix + s_trans:.2f}\n"
    )
    
    return texto_menu, InlineKeyboardMarkup(kb)

# ================= ESTADOS =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_CAT, REG_DESC, ADD_FIXED_TYPE, ADD_FIXED_DATA) = range(7)

# ================= HANDLERS =================
async def start(update, context):
    context.user_data.clear()
    texto, kb = get_main_menu()
    if update.callback_query: await update.callback_query.edit_message_text(texto, reply_markup=kb, parse_mode="Markdown")
    else: await update.message.reply_text(texto, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

# --- REGISTRO PASSO A PASSO ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")]]
    await query.edit_message_text("🏦 **Passo 1:** É um gasto ou ganho?", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Passo 2:** Qual o valor?")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        tipo = context.user_data["temp_type"]
        cats = db["categories"].get(tipo, [])
        kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
        await update.message.reply_text("📂 **Passo 3:** Escolha a Categoria:", reply_markup=InlineKeyboardMarkup(kb))
        return REG_CAT
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    kb = [[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]
    await query.edit_message_text("✍️ **Passo 4:** Descrição (ex: Uber, Janta):", reply_markup=InlineKeyboardMarkup(kb))
    return REG_DESC

async def reg_finish(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    db["transactions"].append({
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["temp_type"],
        "value": context.user_data["temp_value"],
        "category": context.user_data["temp_cat"],
        "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "description": desc
    })
    save_db(db)
    texto, kb = get_main_menu()
    msg = "✅ Registro salvo e saldo atualizado!"
    if update.callback_query: await update.callback_query.message.reply_text(msg, reply_markup=kb)
    else: await update.message.reply_text(msg, reply_markup=kb)
    return ConversationHandler.END

# --- GESTÃO DE FIXOS ---
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Add Novo Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    txt = "📌 **GESTÃO DE FIXOS (Mensais):**\n"
    for f in db["fixed"]:
        txt += f"\n{'📈' if f['type'] == 'ganho' else '📉'} {f['name']}: R$ {f['value']:.2f}"
    await query.edit_message_text(txt if db["fixed"] else "Nenhum fixo cadastrado.", reply_markup=InlineKeyboardMarkup(kb))

async def add_fixed_start(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📈 GANHO (Ex: Salário)", callback_data="fix_ganho")], [InlineKeyboardButton("📉 GASTO (Ex: Aluguel)", callback_data="fix_gasto")]]
    await query.edit_message_text("O que deseja fixar?", reply_markup=InlineKeyboardMarkup(kb))
    return ADD_FIXED_TYPE

async def add_fixed_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["fix_type"] = query.data.split("_")[1]
    await query.edit_message_text("Digite: `NOME VALOR` (Ex: Salário 3000)")
    return ADD_FIXED_DATA

async def add_fixed_save(update, context):
    try:
        parts = update.message.text.rsplit(" ", 1)
        db["fixed"].append({"name": parts[0], "value": float(parts[1].replace(',','.')), "type": context.user_data["fix_type"]})
        save_db(db); await update.message.reply_text("✅ Fixo cadastrado!"); return await start(update, context)
    except: await update.message.reply_text("❌ Erro. Use: Nome Valor"); return ConversationHandler.END

# --- EXPORTAR CSV ---
async def export_csv(update, context):
    query = update.callback_query; await query.answer()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Data", "Tipo", "Categoria", "Valor", "Descrição"])
    for t in db["transactions"]: writer.writerow([t["date"], t["type"], t["category"], t["value"], t["description"]])
    buf = io.BytesIO(output.getvalue().encode('utf-8')); buf.name = "financas.csv"
    await query.message.reply_document(document=buf, caption="📂 Histórico completo!")

async def cancel(update, context): await start(update, context); return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    reg_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type, pattern="^type_")],
            REG_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_value)],
            REG_CAT: [CallbackQueryHandler(reg_cat, pattern="^cat_")],
            REG_DESC: [CallbackQueryHandler(reg_finish, pattern="^desc_"), MessageHandler(filters.TEXT & ~filters.COMMAND, reg_finish)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    
    fix_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")],
        states={
            ADD_FIXED_TYPE: [CallbackQueryHandler(add_fixed_type, pattern="^fix_")],
            ADD_FIXED_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_fixed_save)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start)); app.add_handler(reg_h); app.add_handler(fix_h)
    app.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$")); app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    print("🚀 V6.9 (SALDO DINÂMICO) ONLINE!")
    app.run_polling()
