import os
import sys
import json
import logging
import uuid
import threading
import io
import csv
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
try:
    import httpx
    import matplotlib
    matplotlib.use('Agg') 
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    print("⚠️ Instalando dependências (Matplotlib, ReportLab)...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx", "matplotlib", "reportlab"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
DB_FILE = "finance_ultimate.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= SERVIDOR WEB =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"BOT V3 ULTIMATE ONLINE")
    try: HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except: pass

threading.Thread(target=start_web_server, daemon=True).start()

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra", "Investimento"], "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "Mercado"]}, 
        "fixed_items": [], 
        "goals": [],
        "bills": [] # Nova tabela de Contas a Pagar
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS VISUAIS =================
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, REG_PHOTO, NEW_CAT_NAME, ADD_FIXED, ADD_GOAL, ADD_BILL) = range(9)

def create_progress_bar(current, total, length=10):
    if total == 0: return "░" * length
    percent = min(1.0, current / total)
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(percent * 100)}%"

def get_main_menu():
    # Verifica Saldo para dar Conquista
    ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    saldo = ganhos - gastos
    badge = "🥉"
    if saldo > 1000: badge = "🥈"
    if saldo > 5000: badge = "🥇"
    if saldo > 10000: badge = "🏆"
    if saldo < 0: badge = "💸"

    kb = [
        [InlineKeyboardButton("📝 Novo Registro", callback_data="start_reg")],
        [InlineKeyboardButton("🧠 Coach IA", callback_data="ai_coach"), InlineKeyboardButton("📅 Contas a Pagar", callback_data="menu_bills")],
        [InlineKeyboardButton("📊 Gráficos", callback_data="chart_pie"), InlineKeyboardButton("📄 Relatório PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("🎯 Metas Visuais", callback_data="menu_goals"), InlineKeyboardButton("🔄 Fixos", callback_data="menu_fixed")],
        [InlineKeyboardButton("🗑️ Excluir", callback_data="menu_delete"), InlineKeyboardButton("📂 CSV", callback_data="export_csv")]
    ]
    return InlineKeyboardMarkup(kb), badge

def generate_pdf_report():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "Relatório Financeiro Ultimate")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    y = height - 100
    c.drawString(50, y, "DATA | TIPO | CATEGORIA | VALOR | DESCRIÇÃO")
    y -= 20
    c.line(50, y+15, 550, y+15)
    
    for t in reversed(db["transactions"][-30:]): # Últimas 30
        if y < 50:
            c.showPage()
            y = height - 50
        
        tipo = "ENTRADA" if t['type'] == 'ganho' else "SAÍDA"
        c.drawString(50, y, f"{t['date']} | {tipo} | {t['category']} | R$ {t['value']:.2f}")
        c.drawString(50, y-10, f"Obs: {t['description']}")
        y -= 30
        
    c.save()
    buffer.seek(0)
    return buffer

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb, badge = get_main_menu()
    text = f"🤖 **FINANCEIRO ULTIMATE V3** {badge}\n\nOtimize sua vida financeira!\nSeu Status Atual: {badge}"
    
    if update.callback_query:
        await update.callback_query.answer()
        try: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except: await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

# --- 1. REGISTRO COM FOTO ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")], [InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]]
    await query.edit_message_text("**Passo 1: Tipo de Registro**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Valor:** (Ex: 25.90)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        tipo = context.user_data["temp_type"]
        cats = db["categories"].get(tipo, [])
        kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
        kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])
        await update.message.reply_text("**Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_CAT
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    if query.data == "new_cat": await query.edit_message_text("✍️ **Nome da categoria:**"); return NEW_CAT_NAME
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    await query.edit_message_text("**Descrição:** (Digite ou clique em Pular)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]), parse_mode="Markdown")
    return REG_DESC

async def new_cat_save(update, context):
    nome, tipo = update.message.text, context.user_data["temp_type"]
    if nome not in db["categories"][tipo]: db["categories"][tipo].append(nome); save_db(db)
    context.user_data["temp_cat"] = nome
    await update.message.reply_text("**Descrição:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]), parse_mode="Markdown")
    return REG_DESC

async def reg_desc(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    context.user_data["temp_desc"] = desc
    # Pergunta da FOTO
    kb = [[InlineKeyboardButton("📸 Enviar Foto", callback_data="photo_yes"), InlineKeyboardButton("⏩ Sem Foto", callback_data="photo_no")]]
    msg_txt = "**📸 Deseja anexar um comprovante?**\nEnvie a foto agora ou clique em 'Sem Foto'."
    if update.callback_query: await update.callback_query.edit_message_text(msg_txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(msg_txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_PHOTO

async def reg_photo(update, context):
    file_id = None
    if update.message and update.message.photo:
        file_id = update.message.photo[-1].file_id
    
    item = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["temp_type"],
        "value": context.user_data["temp_value"],
        "category": context.user_data["temp_cat"],
        "description": context.user_data["temp_desc"],
        "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "receipt": file_id
    }
    db["transactions"].append(item); save_db(db)
    
    kb, _ = get_main_menu()
    await (update.message or update.callback_query.message).reply_text(f"✅ **Registrado!**\nR$ {item['value']:.2f} - {item['category']}", reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

# --- 2. COACH IA (SIMULADO) ---
async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    ganho = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    gasto = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    saldo = ganho - gasto
    
    msg = "🧠 **COACH VIRTUAL DIZ:**\n\n"
    if gasto == 0: msg += "Você ainda não gastou nada (ou esqueceu de anotar). Comece a registrar!"
    elif saldo < 0: msg += f"🚨 **ALERTA VERMELHO!**\nVocê está no prejuízo de R$ {saldo:.2f}. Pare de comprar coisas supérfluas agora mesmo ou vai se endividar!"
    elif gasto > (ganho * 0.8): msg += "⚠️ **Cuidado!**\nVocê já gastou mais de 80% do que ganhou. Segura a onda no final do mês."
    elif saldo > (ganho * 0.3): msg += "🏆 **Parabéns!**\nVocê está poupando mais de 30% da sua renda. Continue assim e invista esse dinheiro!"
    else: msg += "📊 **Situação Normal.**\nSuas contas parecem equilibradas, mas fique de olho nos gastos com Lazer."
    
    await query.edit_message_text(msg, reply_markup=get_main_menu()[0], parse_mode="Markdown")

# --- 3. RELATÓRIO PDF ---
async def export_pdf(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("🖨️ Gerando PDF...")
    pdf = generate_pdf_report()
    pdf.name = "relatorio_ultimate.pdf"
    await query.message.reply_document(document=pdf, caption="📄 **Seu Relatório Profissional**", reply_markup=get_main_menu()[0])

# --- 4. CONTAS A PAGAR (NOVO) ---
async def menu_bills(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Adicionar Conta", callback_data="add_bill_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    text = "📅 **CONTAS A PAGAR:**\n\n"
    if not db["bills"]: text += "_Nenhuma conta cadastrada._"
    
    for b in db["bills"]:
        text += f"🗓️ Dia {b['day']}: **{b['name']}** (R$ {b['value']:.2f})\n"
        
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_bill_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `DIA NOME VALOR`\nEx: `10 Internet 100`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return ADD_BILL

async def add_bill_save(update, context):
    try:
        parts = update.message.text.split(" ")
        day = int(parts[0])
        val = float(parts[-1])
        name = " ".join(parts[1:-1])
        db["bills"].append({"day": day, "name": name, "value": val})
        db["bills"].sort(key=lambda x: x['day'])
        save_db(db)
        await update.message.reply_text("✅ Conta Agendada!", reply_markup=get_main_menu()[0])
    except: await update.message.reply_text("❌ Erro. Use: `10 Aluguel 1200`")
    return ConversationHandler.END

# --- 5. METAS VISUAIS ---
async def menu_goals(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    text = "🎯 **METAS MENSAIS (Visual):**\n\n"
    
    gastos_mes = {} 
    for t in db["transactions"]:
        if t['type'] == 'gasto': gastos_mes[t['category']] = gastos_mes.get(t['category'], 0) + t['value']
        
    for g in db["goals"]:
        atual = gastos_mes.get(g['category'], 0)
        bar = create_progress_bar(atual, g['limit'])
        text += f"**{g['category']}**\n{bar} R$ {atual:.0f}/{g['limit']}\n\n"
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `CATEGORIA VALOR`\nEx: `Lazer 500`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return ADD_GOAL

async def add_goal_save(update, context):
    try:
        cat, val = update.message.text.rsplit(" ", 1)
        db["goals"] = [g for g in db["goals"] if g['category'] != cat]
        db["goals"].append({"category": cat, "limit": float(val)})
        save_db(db)
        await update.message.reply_text("✅ Meta Salva!", reply_markup=get_main_menu()[0])
    except: await update.message.reply_text("Erro.")
    return ConversationHandler.END

# --- OUTROS (FIXOS, CSV, CHART, DELETE, CANCEL) ---
async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    gastos = {}
    for t in db["transactions"]:
        if t["type"] == "gasto": gastos[t["category"]] = gastos.get(t["category"], 0) + t["value"]
    if not gastos: return await query.edit_message_text("📭 Sem dados.", reply_markup=get_main_menu()[0])
    
    plt.figure(figsize=(6, 6))
    plt.pie(gastos.values(), labels=gastos.keys(), autopct='%1.1f%%', startangle=140)
    plt.title("Gastos")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(photo=buf, caption="📊 **Análise Gráfica**", reply_markup=get_main_menu()[0])

async def export_csv(update, context):
    query = update.callback_query; await query.answer()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Data", "Tipo", "Categoria", "Valor", "Descricao"])
    for t in db["transactions"]: writer.writerow([t["date"], t["type"], t["category"], str(t["value"]), t["description"]])
    output.seek(0)
    bytes_csv = io.BytesIO(output.getvalue().encode('utf-8')); bytes_csv.name = "extrato.csv"
    await query.message.reply_document(document=bytes_csv, caption="📂 CSV Gerado", reply_markup=get_main_menu()[0])

async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Novo Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    text = "📌 **FIXOS (Processar no Menu Principal):**\n"
    for f in db["fixed_items"]: text += f"- {f['name']}: R$ {f['value']:.2f}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `TIPO NOME VALOR`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return ADD_FIXED

async def add_fixed_save(update, context):
    try:
        parts = update.message.text.split(" ")
        db["fixed_items"].append({"type": parts[0].lower(), "name": " ".join(parts[1:-1]), "value": float(parts[-1])})
        save_db(db)
        await update.message.reply_text("✅ Fixo Salvo!", reply_markup=get_main_menu()[0])
    except: await update.message.reply_text("Erro.")
    return ConversationHandler.END

async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    kb = []
    for t in reversed(db["transactions"][-5:]): kb.append([InlineKeyboardButton(f"❌ R$ {t['value']} - {t['description']}", callback_data=f"kill_{t['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Apagar Recentes:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db)
    await query.edit_message_text("✅ Apagado!", reply_markup=get_main_menu()[0])

async def cancel(update, context):
    await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Conversations
    conv_reg = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type)], REG_VALUE: [MessageHandler(filters.TEXT, reg_value)],
            REG_CAT: [CallbackQueryHandler(reg_cat)], NEW_CAT_NAME: [MessageHandler(filters.TEXT, new_cat_save)],
            REG_DESC: [CallbackQueryHandler(reg_desc), MessageHandler(filters.TEXT, reg_desc)],
            REG_PHOTO: [CallbackQueryHandler(reg_photo), MessageHandler(filters.PHOTO, reg_photo)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    conv_goal = ConversationHandler(entry_points=[CallbackQueryHandler(add_goal_start, pattern="^add_goal_start$")], states={ADD_GOAL: [MessageHandler(filters.TEXT, add_goal_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    conv_fixed = ConversationHandler(entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")], states={ADD_FIXED: [MessageHandler(filters.TEXT, add_fixed_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    conv_bill = ConversationHandler(entry_points=[CallbackQueryHandler(add_bill_start, pattern="^add_bill_start$")], states={ADD_BILL: [MessageHandler(filters.TEXT, add_bill_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_reg); app.add_handler(conv_goal); app.add_handler(conv_fixed); app.add_handler(conv_bill)
    
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
    app.add_handler(CallbackQueryHandler(export_pdf, pattern="^export_pdf$"))
    app.add_handler(CallbackQueryHandler(menu_bills, pattern="^menu_bills$"))
    app.add_handler(CallbackQueryHandler(chart_pie, pattern="^chart_pie$"))
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    
    print("🚀 BOT V3 ULTIMATE RODANDO...")
    app.run_polling()
