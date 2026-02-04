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
DB_FILE = "finance_v7_5_final.json"

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Saúde", "Casa"]}, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA"],
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
 ADD_FIXED_TYPE, ADD_FIXED_DATA, ADD_GOAL, NEW_CAT_TYPE, NEW_CAT_NAME) = range(11)

# ================= CÁLCULOS DE SALDO REAL =================
def calculate_balance():
    mes_atual = datetime.now().strftime("%m/%Y")
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_atual in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    saldo = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    return saldo, (ganhos_fixos + trans_ganhos), (gastos_fixos + trans_gastos)

# ================= MENU PRINCIPAL =================
def get_main_menu():
    saldo, total_in, total_out = calculate_balance()
    mode_txt = "🤡 Zoeiro: ON" if db["config"]["zoeiro_mode"] else "🤖 IA: Ativa"
    status = "💰" if saldo >= 0 else "🚨"
    
    kb = [
        [InlineKeyboardButton("📝 REGISTRAR", callback_data="start_reg"), InlineKeyboardButton("🔍 RAIO-X", callback_data="full_report")],
        [InlineKeyboardButton("📌 FIXOS", callback_data="menu_fixed"), InlineKeyboardButton("🎯 METAS", callback_data="menu_goals")],
        [InlineKeyboardButton("📊 GRÁFICO", callback_data="chart_pie"), InlineKeyboardButton("📄 PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("🆚 Mês x Mês", callback_data="compare_months"), InlineKeyboardButton("📂 CSV", callback_data="export_csv")],
        [InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach"), InlineKeyboardButton("➕ CAT", callback_data="menu_cat")],
        [InlineKeyboardButton(mode_txt, callback_data="toggle_mode"), InlineKeyboardButton("🗑️ EXCLUIR", callback_data="menu_delete")]
    ]
    
    texto = (f"🤖 **FINANCEIRO V7.5**\n\n{status} **Saldo Real:** R$ {saldo:.2f}\n"
             f"📈 Entradas: R$ {total_in:.2f} | 📉 Saídas: R$ {total_out:.2f}\n"
             f"━━━━━━━━━━━━━━")
    return texto, InlineKeyboardMarkup(kb)

# ================= HANDLERS =================
async def start(update, context):
    context.user_data.clear()
    t, kb = get_main_menu()
    if update.callback_query: await update.callback_query.edit_message_text(t, reply_markup=kb, parse_mode="Markdown")
    else: await update.message.reply_text(t, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

# --- REGISTRO PASSO A PASSO (COMPLETO) ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")], [InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")]]
    await query.edit_message_text("🏦 **Gasto ou Ganho?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Valor?**")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        kb = [[InlineKeyboardButton(w, callback_data=f"wallet_{w}")] for w in db["wallets"]]
        await update.message.reply_text("💳 **Carteira?**", reply_markup=InlineKeyboardMarkup(kb))
        return REG_WALLET
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_wallet(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_wallet"] = query.data.replace("wallet_", "")
    if context.user_data["temp_type"] == "gasto":
        kb = [[InlineKeyboardButton("À Vista", callback_data="parc_1")], [InlineKeyboardButton("2x", callback_data="parc_2"), InlineKeyboardButton("12x", callback_data="parc_12")]]
        await query.edit_message_text("📅 **Parcelado?**", reply_markup=InlineKeyboardMarkup(kb))
        return REG_PARCELAS
    else: context.user_data["temp_parc"] = 1; return await ask_cat(query, context)

async def reg_parcelas(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_parc"] = int(query.data.replace("parc_", ""))
    return await ask_cat(query, context)

async def ask_cat(query, context):
    cats = db["categories"][context.user_data["temp_type"]]
    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await query.edit_message_text("📂 **Categoria:**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_CAT

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    await query.edit_message_text("✍️ **Descrição:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]))
    return REG_DESC

async def reg_finish(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    parc = context.user_data.get("temp_parc", 1)
    val = context.user_data["temp_value"] / parc
    for i in range(parc):
        db["transactions"].append({
            "id": str(uuid.uuid4())[:8], "type": context.user_data["temp_type"], "value": val,
            "category": context.user_data["temp_cat"], "wallet": context.user_data["temp_wallet"],
            "description": f"{desc} ({i+1}/{parc})" if parc > 1 else desc,
            "date": (datetime.now() + timedelta(days=30*i)).strftime("%d/%m/%Y %H:%M")
        })
    save_db(db); await (update.callback_query.message.reply_text if update.callback_query else update.message.reply_text)("✅ Salvo!", reply_markup=get_main_menu()[1]); return ConversationHandler.END

# --- RAIO-X DETALHADO (RESTAURADO) ---
async def full_report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    if not trans: return await query.edit_message_text("📭 Sem gastos este mês.")
    
    res = {}
    total = sum(t['value'] for t in trans)
    for t in trans: res[t['category']] = res.get(t['category'], 0) + t['value']
    
    msg = f"🔍 **RAIO-X DE {mes}**\n\nTotal Gasto: R$ {total:.2f}\n\n"
    for c, v in sorted(res.items(), key=lambda x:x[1], reverse=True):
        msg += f"🔸 {c}: R$ {v:.2f} ({ (v/total)*100 :.1f}%)\n"
    await query.edit_message_text(msg, reply_markup=get_main_menu()[1])

# --- GRÁFICO PIZZA (RESTAURADO) ---
async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    if not trans: return await query.edit_message_text("❌ Sem dados.")
    
    data = {}
    for t in trans: data[t['category']] = data.get(t['category'], 0) + t['value']
    plt.figure(figsize=(6, 6)); plt.pie(data.values(), labels=data.keys(), autopct='%1.1f%%'); plt.title(f"Gastos {mes}")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(photo=buf, caption=f"📊 Pizza de {mes}")

# --- FIXOS (SALÁRIO + CONTAS) ---
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Add Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    txt = "📌 **GESTÃO DE FIXOS:**\n"
    for f in db["fixed"]: txt += f"\n{'📈' if f['type'] == 'ganho' else '📉'} {f['name']}: R$ {f['value']:.2f}"
    await query.edit_message_text(txt if db["fixed"] else "Vazio.", reply_markup=InlineKeyboardMarkup(kb))

async def add_fixed_start(update, context):
    kb = [[InlineKeyboardButton("📈 GANHO (Salário)", callback_data="fix_ganho")], [InlineKeyboardButton("📉 GASTO (Contas)", callback_data="fix_gasto")]]
    await update.callback_query.edit_message_text("Fixar Ganho ou Gasto?", reply_markup=InlineKeyboardMarkup(kb))
    return ADD_FIXED_TYPE

async def add_fixed_save(update, context):
    try:
        p = update.message.text.rsplit(" ", 1)
        db["fixed"].append({"name": p[0], "value": float(p[1]), "type": context.user_data["fix_type"]})
        save_db(db); await update.message.reply_text("✅ Fixo salvo!", reply_markup=get_main_menu()[1])
    except: await update.message.reply_text("Erro. Ex: Salário 3000")
    return ConversationHandler.END

# --- OUTROS (PDF, CSV, MÊS X MÊS, IA) ---
async def compare_months(update, context):
    query = update.callback_query; await query.answer()
    now = datetime.now(); m_at = now.strftime("%m/%Y"); m_pas = (now.replace(day=1)-timedelta(days=1)).strftime("%m/%Y")
    g_at = sum(t['value'] for t in db["transactions"] if m_at in t['date'] and t['type']=='gasto')
    g_pas = sum(t['value'] for t in db["transactions"] if m_pas in t['date'] and t['type']=='gasto')
    diff = g_at - g_pas
    await query.edit_message_text(f"🆚 **MÊS X MÊS:**\n\n📅 Ant: R$ {g_pas:.2f}\n📅 Atual: R$ {g_at:.2f}\n\nDif: R$ {diff:.2f}", reply_markup=get_main_menu()[1])

async def export_pdf(update, context):
    query = update.callback_query; await query.answer(); buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(100, 750, f"RELATÓRIO PDF - {datetime.now().strftime('%d/%m/%Y')}")
    y = 700
    for t in db["transactions"][-15:]: c.drawString(100, y, f"{t['date']} - {t['category']} - R$ {t['value']:.2f}"); y -= 20
    c.save(); buf.seek(0); buf.name = "financas.pdf"; await query.message.reply_document(document=buf)

async def ai_coach(update, context):
    await update.callback_query.edit_message_text("🧠 Analisando..."); t_text = str(db["transactions"][-10:])
    res = model.generate_content(f"Conselho financeiro curto para: {t_text}"); await update.callback_query.edit_message_text(f"🧠 **IA:** {res.text}", reply_markup=get_main_menu()[1])

async def export_csv(update, context):
    output = io.StringIO(); w = csv.writer(output); w.writerow(["Data", "Tipo", "Cat", "Valor", "Desc"])
    for t in db["transactions"]: w.writerow([t["date"], t["type"], t["category"], t["value"], t["description"]])
    buf = io.BytesIO(output.getvalue().encode('utf-8')); buf.name = "financas.csv"; await update.callback_query.message.reply_document(document=buf)

async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    reg_h = ConversationHandler(entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")], states={REG_TYPE: [CallbackQueryHandler(reg_type)], REG_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_value)], REG_WALLET: [CallbackQueryHandler(reg_wallet)], REG_PARCELAS: [CallbackQueryHandler(reg_parcelas)], REG_CAT: [CallbackQueryHandler(reg_cat)], REG_DESC: [CallbackQueryHandler(reg_finish), MessageHandler(filters.TEXT & ~filters.COMMAND, reg_finish)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    fix_h = ConversationHandler(entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")], states={ADD_FIXED_TYPE: [CallbackQueryHandler(lambda u,c: (c.user_data.update({'fix_type': u.callback_query.data.split('_')[1]}), u.callback_query.edit_message_text("Digite: Nome Valor")) or ADD_FIXED_DATA)], ADD_FIXED_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_fixed_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    app.add_handler(CommandHandler("start", start)); app.add_handler(reg_h); app.add_handler(fix_h)
    app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$")); app.add_handler(CallbackQueryHandler(chart_pie, pattern="^chart_pie$")); app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
    app.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$")); app.add_handler(CallbackQueryHandler(export_pdf, pattern="^export_pdf$")); app.add_handler(CallbackQueryHandler(compare_months, pattern="^compare_months$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: (db["config"].update({"zoeiro_mode": not db["config"]["zoeiro_mode"]}), save_db(db), start(u,c)), pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    app.run_polling()
