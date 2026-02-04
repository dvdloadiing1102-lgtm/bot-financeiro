import os
import json
import logging
import uuid
import io
import csv
from datetime import datetime, timedelta

import google.generativeai as genai
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
GEMINI_KEY = "AIzaSyAV-9NqZ60BNapV4-ADQ1gSRffRkpeu4-w" 
DB_FILE = "finance_v17_database.json"

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

# ================= ESTADOS =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_CAT, REG_DESC, 
 NEW_CAT_TYPE, NEW_CAT_NAME) = range(7)

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
    txt = f"🤖 **FINANCEIRO V17.0**\n\n💰 **Saldo Real:** R$ {saldo:.2f}\n📈 Ganhos: R$ {t_in:.2f}\n📉 Gastos: R$ {t_out:.2f}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= RAIO-X (CORRIGIDO) =================
async def full_report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    saldo, t_in, t_out = calculate_balance()
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    cats = {}
    for t in trans: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    msg = f"🔍 **RAIO-X DE {mes}**\n\n📈 Entradas: R$ {t_in:.2f}\n📉 Saídas: R$ {t_out:.2f}\n⚖️ **Saldo: R$ {saldo:.2f}**\n\n**DETALHES:**\n"
    for c, v in sorted(cats.items(), key=lambda x:x[1], reverse=True):
        msg += f"🔸 {c}: R$ {v:.2f}\n"
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]), parse_mode="Markdown")
    return ConversationHandler.END

# ================= CATEGORIA (CORRIGIDO) =================
async def menu_cat(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="ncat_gasto"), InlineKeyboardButton("Ganho", callback_data="ncat_ganho")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    await query.edit_message_text("Adicionar categoria em qual lista?", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def new_cat_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["ncat_t"] = query.data.split("_")[1]
    await query.edit_message_text("✍️ Digite o nome da nova categoria:")
    return NEW_CAT_NAME

async def new_cat_save(update, context):
    tipo = context.user_data["ncat_t"]
    db["categories"][tipo].append(update.message.text.strip())
    save_db(db); await update.message.reply_text("✅ Categoria adicionada!"); return await start(update, context)

# ================= EXCLUIR (CORRIGIDO) =================
async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton(f"❌ {t['value']} - {t['category']}", callback_data=f"kill_{t['id']}")] for t in reversed(db["transactions"][-5:])]
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Selecione para apagar:**", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db); return await start(update, context)

# ================= REGISTRO (CORRIGIDO) =================
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="reg_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="reg_ganho")]]
    await query.edit_message_text("🏦 **Tipo de registro:**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Qual o valor?**")
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
    await query.edit_message_text("📂 **Qual categoria?**", reply_markup=InlineKeyboardMarkup(kb))
    return REG_CAT

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    await query.edit_message_text("✍️ **Descrição?**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="skip_desc")]]))
    return REG_DESC

async def reg_finish(update, context):
    desc = "Sem descrição" if (update.callback_query and update.callback_query.data == "skip_desc") else update.message.text
    db["transactions"].append({
        "id": str(uuid.uuid4())[:8], "type": context.user_data["temp_type"], "value": context.user_data["temp_value"],
        "category": context.user_data["temp_cat"], "wallet": context.user_data["temp_wallet"],
        "description": desc, "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_db(db); return await start(update, context)

async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= IA E FIXOS (CORRIGIDO) =================
async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("🧠 **Gemini analisando...**")
    saldo, t_in, t_out = calculate_balance()
    prompt = "Consultor financeiro. " + ("Sarcástico" if db["config"]["zoeiro_mode"] else "Sério")
    try:
        resp = model_ai.generate_content(f"{prompt}. Saldo:{saldo}")
        await query.edit_message_text(f"🧠 **IA:**\n\n{resp.text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
    except: await query.edit_message_text("❌ Erro na IA.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
    return ConversationHandler.END

async def toggle_mode(update, context):
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db); return await start(update, context)

# ================= MENU FIXOS (NOVO) =================
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    fixos_ganho = [f for f in db["fixed"] if f['type'] == 'ganho']
    fixos_gasto = [f for f in db["fixed"] if f['type'] == 'gasto']
    
    msg = "📌 **DESPESAS FIXAS**\n\n"
    msg += "**Ganhos Fixos:**\n"
    for f in fixos_ganho:
        msg += f"✅ {f['description']}: R$ {f['value']:.2f}\n"
    msg += "\n**Gastos Fixos:**\n"
    for f in fixos_gasto:
        msg += f"❌ {f['description']}: R$ {f['value']:.2f}\n"
    
    kb = [
        [InlineKeyboardButton("➕ Adicionar Ganho Fixo", callback_data="add_fixed_ganho")],
        [InlineKeyboardButton("➕ Adicionar Gasto Fixo", callback_data="add_fixed_gasto")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= GRÁFICO (NOVO) =================
async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📊 **Gerando gráfico...**")
    
    mes = datetime.now().strftime("%m/%Y")
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    cats = {}
    for t in trans:
        cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    if not cats:
        await query.edit_message_text("❌ Sem dados para gerar gráfico.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
        return ConversationHandler.END
    
    plt.figure(figsize=(8, 6))
    plt.pie(cats.values(), labels=cats.keys(), autopct='%1.1f%%', startangle=90)
    plt.title(f"Gastos por Categoria - {mes}")
    
    img_path = "chart_temp.png"
    plt.savefig(img_path, bbox_inches='tight')
    plt.close()
    
    with open(img_path, 'rb') as img:
        await query.message.reply_photo(photo=img, caption="📊 Gráfico de Gastos")
    
    os.remove(img_path)
    await query.edit_message_text("✅ Gráfico enviado!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
    return ConversationHandler.END

# ================= EXPORTAR PDF (NOVO) =================
async def export_pdf(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📄 **Gerando PDF...**")
    
    mes = datetime.now().strftime("%m/%Y")
    saldo, t_in, t_out = calculate_balance()
    
    pdf_path = "relatorio_financeiro.pdf"
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, f"Relatório Financeiro - {mes}")
    
    c.setFont("Helvetica", 12)
    c.drawString(50, 720, f"Saldo: R$ {saldo:.2f}")
    c.drawString(50, 700, f"Entradas: R$ {t_in:.2f}")
    c.drawString(50, 680, f"Saídas: R$ {t_out:.2f}")
    
    c.save()
    
    with open(pdf_path, 'rb') as pdf:
        await query.message.reply_document(document=pdf, filename=pdf_path)
    
    os.remove(pdf_path)
    await query.edit_message_text("✅ PDF enviado!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
    return ConversationHandler.END

# ================= EXPORTAR CSV (NOVO) =================
async def export_csv(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📂 **Gerando CSV...**")
    
    csv_path = "transacoes_financeiras.csv"
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['ID', 'Tipo', 'Valor', 'Categoria', 'Carteira', 'Descrição', 'Data']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for t in db["transactions"]:
            writer.writerow({
                'ID': t['id'],
                'Tipo': t['type'],
                'Valor': f"R$ {t['value']:.2f}",
                'Categoria': t['category'],
                'Carteira': t['wallet'],
                'Descrição': t['description'],
                'Data': t['date']
            })
    
    with open(csv_path, 'rb') as csv_file:
        await query.message.reply_document(document=csv_file, filename=csv_path)
    
    os.remove(csv_path)
    await query.edit_message_text("✅ CSV enviado!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]))
    return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    reg_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type)],
            REG_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_value)],
            REG_WALLET: [CallbackQueryHandler(reg_wallet)],
            REG_CAT: [CallbackQueryHandler(reg_cat)],
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_h); app.add_handler(cat_h)
    app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    app.add_handler(CallbackQueryHandler(chart_pie, pattern="^chart_pie$"))
    app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
    app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(export_pdf, pattern="^export_pdf$"))
    app.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    app.run_polling(drop_pending_updates=True)
