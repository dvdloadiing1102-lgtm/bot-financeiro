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
    import matplotlib
    matplotlib.use('Agg') 
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    print("⚠️ Instalando dependências...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx", "matplotlib", "reportlab", "google-generativeai"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 

# 👇 SUA CHAVE GEMINI JÁ ESTÁ AQUI 👇
GEMINI_KEY = "AIzaSyAV-9NqZ60BNapV4-ADQ1gSRffRkpeu4-w" 

DB_FILE = "finance_v6_ai.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configura Gemini
if GEMINI_KEY != "COLE_SUA_KEY_AQUI":
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash') 
    AI_ACTIVE = True
else:
    AI_ACTIVE = False

# ================= ROASTS (OFFLINE) =================
ROASTS_OFFLINE = {
    "gasto": ["💸 Dinheiro não aceita desaforo!", "💸 O agiota tá orgulhoso.", "💸 Vai morar debaixo da ponte assim."],
    "ganho": ["💰 O milagre aconteceu!", "💰 Não gasta tudo em besteira!", "💰 Glória a Deus!"]
}

# ================= SERVIDOR WEB =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"BOT V6 AI ONLINE")
    try: HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except: pass
threading.Thread(target=start_web_server, daemon=True).start()

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra", "Investimento"], "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "Mercado", "Saúde", "Compras"]}, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "VR/VA", "Inter"],
        "goals": [],
        "bills": [],
        "config": {"zoeiro_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_PARCELAS, REG_CAT, REG_DESC, REG_PHOTO, ADD_FIXED, ADD_GOAL, ADD_BILL) = range(10)

def create_progress_bar(current, total, length=8):
    if total == 0: return "░" * length
    percent = min(1.0, current / total)
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(percent * 100)}%"

def get_main_menu():
    mode_text = "🤡 Mode: ON" if db["config"]["zoeiro_mode"] else "🤖 Mode: OFF"
    kb = [
        [InlineKeyboardButton("📝 NOVO REGISTRO", callback_data="start_reg")],
        [InlineKeyboardButton("🧠 ANÁLISE IA", callback_data="ai_coach"), InlineKeyboardButton("📅 Contas", callback_data="menu_bills")],
        [InlineKeyboardButton("🆚 Mês x Mês", callback_data="compare_months"), InlineKeyboardButton(f"{mode_text}", callback_data="toggle_mode")],
        [InlineKeyboardButton("📊 Gráficos", callback_data="chart_pie"), InlineKeyboardButton("📄 PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("🗑️ Excluir", callback_data="menu_delete"), InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")]
    ]
    return InlineKeyboardMarkup(kb)

def generate_pdf_report():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 16); c.drawString(50, height-50, "Relatório Financeiro V6 AI")
    c.setFont("Helvetica", 10); c.drawString(50, height-70, f"Gerado em: {datetime.now().strftime('%d/%m/%Y')}")
    y = height - 100; c.drawString(50, y, "DATA | TIPO | CAT | VALOR | DESC")
    y -= 20; c.line(50, y+15, 550, y+15)
    for t in reversed(db["transactions"][-30:]):
        if y < 50: c.showPage(); y = height - 50
        tipo = "ENT" if t['type']=='ganho' else "SAI"
        c.drawString(50, y, f"{t['date'][:10]} | {tipo} | {t['category'][:10]} | R$ {t['value']:.2f} | {t['description'][:20]}")
        y -= 20
    c.save(); buffer.seek(0)
    return buffer

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = get_main_menu()
    text = "🤖 **FINANCEIRO V6 (COM GEMINI IA)**\n\nAgora seu bot pensa de verdade!\nSelecione uma opção abaixo:"
    if update.callback_query:
        await update.callback_query.answer()
        try: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except: await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

async def toggle_mode(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]; save_db(db)
    msg = "🤡 **MODO ZOEIRO ATIVADO!**" if db["config"]["zoeiro_mode"] else "🤖 **Modo Sério Ativado.**"
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- REGISTRO ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    await query.edit_message_text("**O que vamos registrar?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Qual o valor?**\nEx: `150.90`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]), parse_mode="Markdown")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        kb = [[InlineKeyboardButton(w, callback_data=f"wallet_{w}")] for w in db["wallets"]]
        kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])
        await update.message.reply_text("🏦 **Saiu de qual conta?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_WALLET
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_wallet(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_wallet"] = query.data.replace("wallet_", "")
    if context.user_data["temp_type"] == "gasto":
        kb = [[InlineKeyboardButton("1x", callback_data="parc_1"), InlineKeyboardButton("2x", callback_data="parc_2"), InlineKeyboardButton("3x", callback_data="parc_3")], [InlineKeyboardButton("6x", callback_data="parc_6"), InlineKeyboardButton("12x", callback_data="parc_12")]]
        await query.edit_message_text("💳 **Parcelado?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_PARCELAS
    else:
        context.user_data["temp_parc"] = 1; return await ask_category(query, context)

async def reg_parcelas(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_parc"] = int(query.data.replace("parc_", ""))
    return await ask_category(query, context)

async def ask_category(query, context):
    tipo = context.user_data["temp_type"]
    cats = db["categories"].get(tipo, [])
    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await query.edit_message_text("**Escolha a Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_CAT

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    await query.edit_message_text("**Descrição:** (Digite ou clique em Pular)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]), parse_mode="Markdown")
    return REG_DESC

async def reg_desc(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    context.user_data["temp_desc"] = desc
    kb = [[InlineKeyboardButton("📸 Sim", callback_data="photo_yes"), InlineKeyboardButton("⏩ Não", callback_data="photo_no")]]
    msg_txt = "**📸 Deseja anexar foto do comprovante?**"
    if update.callback_query: await update.callback_query.edit_message_text(msg_txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(msg_txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_PHOTO

async def reg_photo_finish(update, context):
    file_id = None
    if update.message and update.message.photo: file_id = update.message.photo[-1].file_id
    
    parc = context.user_data.get("temp_parc", 1)
    val_parc = context.user_data["temp_value"] / parc
    
    for i in range(parc):
        item = {
            "id": str(uuid.uuid4())[:8],
            "type": context.user_data["temp_type"],
            "value": val_parc,
            "category": context.user_data["temp_cat"],
            "wallet": context.user_data["temp_wallet"],
            "description": f"{context.user_data['temp_desc']} ({i+1}/{parc})" if parc > 1 else context.user_data["temp_desc"],
            "date": (datetime.now() + timedelta(days=30*i)).strftime("%d/%m/%Y %H:%M"),
            "receipt": file_id
        }
        db["transactions"].append(item)
    save_db(db)
    
    roast = "✅ Registrado!"
    if db["config"]["zoeiro_mode"]: roast = random.choice(ROASTS_OFFLINE.get(context.user_data["temp_type"], ["💸"]))
    
    msg = f"{roast}\n\nValor: R$ {context.user_data['temp_value']:.2f} ({parc}x)"
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

# --- COACH IA COM GEMINI ---
async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    
    if not AI_ACTIVE:
        await query.edit_message_text("⚠️ **ERRO:** Gemini não configurada.", reply_markup=get_main_menu(), parse_mode="Markdown")
        return

    await query.edit_message_text("🧠 **Analisando suas finanças com IA...**", parse_mode="Markdown")

    transacoes = db["transactions"][-20:]
    dados_texto = "Minhas transações:\n"
    for t in transacoes:
        dados_texto += f"- {t['date']} | {t['type']} | {t['category']} | R$ {t['value']} | {t['description']}\n"
    
    ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    saldo = ganhos - gastos

    dados_texto += f"\nResumo: Ganhos {ganhos}, Gastos {gastos}, Saldo {saldo}."
    
    prompt = "Seja um consultor financeiro motivador."
    if db["config"]["zoeiro_mode"]:
        prompt = "Seja um consultor financeiro sarcástico e zombeteiro. Zombe das compras inúteis do usuário. Seja curto e use gírias brasileiras."

    full_prompt = f"{prompt}\nAnalise esses dados e me dê um conselho curto:\n\n{dados_texto}"

    try:
        response = model.generate_content(full_prompt)
        msg_ia = f"🧠 **COACH IA DIZ:**\n\n{response.text}"
    except Exception as e:
        msg_ia = f"❌ Erro na IA: {e}"

    await query.edit_message_text(msg_ia, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- OUTRAS FUNÇÕES ---
async def compare_months(update, context):
    query = update.callback_query; await query.answer()
    hoje = datetime.now(); mes_atual = hoje.strftime("%m/%Y"); mes_ant = (hoje.replace(day=1) - timedelta(days=1)).strftime("%m/%Y")
    ga = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    gp = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_ant in t['date'])
    diff = ga - gp; icon = "📈" if diff > 0 else "📉"
    msg = f"🆚 **{mes_ant} vs {mes_atual}**\n\nAnt: R$ {gp:.2f}\nAtual: R$ {ga:.2f}\nDif: {icon} R$ {diff:.2f}"
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

async def menu_bills(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Adicionar", callback_data="add_bill_start")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    text = "📅 **CONTAS A PAGAR:**\n" + ("_Vazio_" if not db["bills"] else "")
    for b in db["bills"]: text += f"\n🗓️ Dia {b['day']}: {b['name']} (R$ {b['value']})"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_bill_save(update, context):
    try:
        p = update.message.text.split(" ")
        db["bills"].append({"day": int(p[0]), "name": " ".join(p[1:-1]), "value": float(p[-1])}); db["bills"].sort(key=lambda x:x['day']); save_db(db)
        await update.message.reply_text("✅ Conta Salva!", reply_markup=get_main_menu())
    except: await update.message.reply_text("❌ Erro. Use: `10 Internet 100`")
    return ConversationHandler.END

async def menu_goals(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal_start")], [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]]
    text = "🎯 **METAS:**\n\n"
    gm = {}
    for t in db["transactions"]: 
        if t['type'] == 'gasto': gm[t['category']] = gm.get(t['category'], 0) + t['value']
    for g in db["goals"]:
        atual = gm.get(g['category'], 0)
        text += f"**{g['category']}**: {create_progress_bar(atual, g['limit'])} R${atual:.0f}/{g['limit']}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_save(update, context):
    try:
        cat, val = update.message.text.rsplit(" ", 1)
        db["goals"].append({"category": cat, "limit": float(val)}); save_db(db)
        await update.message.reply_text("✅ Meta Salva!", reply_markup=get_main_menu())
    except: await update.message.reply_text("❌ Erro.")
    return ConversationHandler.END

async def export_pdf(update, context):
    query = update.callback_query; await query.answer()
    await query.message.reply_document(document=generate_pdf_report(), caption="Relatório", reply_markup=get_main_menu())

async def chart_pie(update, context):
    query = update.callback_query; await query.answer(); gastos = {}
    for t in db["transactions"]: 
        if t["type"] == "gasto": gastos[t["category"]] = gastos.get(t["category"], 0) + t["value"]
    if not gastos: return await query.edit_message_text("📭 Sem dados.", reply_markup=get_main_menu())
    plt.figure(figsize=(6, 6)); plt.pie(gastos.values(), labels=gastos.keys(), autopct='%1.1f%%'); plt.title("Gastos")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(photo=buf, caption="📊 Gastos por Categoria", reply_markup=get_main_menu())

async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton(f"❌ {t['value']} - {t['description'][:10]}", callback_data=f"kill_{t['id']}")] for t in reversed(db["transactions"][-5:])]
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Apagar Recentes:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]; save_db(db)
    await query.edit_message_text("✅ Apagado!", reply_markup=get_main_menu())

async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    reg_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type)], REG_VALUE: [MessageHandler(filters.TEXT, reg_value)],
            REG_WALLET: [CallbackQueryHandler(reg_wallet)], REG_PARCELAS: [CallbackQueryHandler(reg_parcelas)],
            REG_CAT: [CallbackQueryHandler(reg_cat)], REG_DESC: [CallbackQueryHandler(reg_desc), MessageHandler(filters.TEXT, reg_desc)],
            REG_PHOTO: [CallbackQueryHandler(reg_photo_finish), MessageHandler(filters.PHOTO, reg_photo_finish)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    conv_bill = ConversationHandler(entry_points=[CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("Digite: `DIA NOME VALOR`") or ADD_BILL, pattern="^add_bill_start$")], states={ADD_BILL: [MessageHandler(filters.TEXT, add_bill_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    conv_goal = ConversationHandler(entry_points=[CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("Digite: `CATEGORIA VALOR`") or ADD_GOAL, pattern="^add_goal_start$")], states={ADD_GOAL: [MessageHandler(filters.TEXT, add_goal_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])

    app.add_handler(CommandHandler("start", start)); app.add_handler(reg_handler); app.add_handler(conv_bill); app.add_handler(conv_goal)
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$")); app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$")); app.add_handler(CallbackQueryHandler(compare_months, pattern="^compare_months$"))
    app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$")); app.add_handler(CallbackQueryHandler(chart_pie, pattern="^chart_pie$")); app.add_handler(CallbackQueryHandler(export_pdf, pattern="^export_pdf$"))
    app.add_handler(CallbackQueryHandler(menu_bills, pattern="^menu_bills$")); app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$")); app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    
    print("🧠 BOT V6 AI RODANDO...")
    app.run_polling()
