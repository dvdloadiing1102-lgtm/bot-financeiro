import os
import sys
import subprocess
import logging
import threading
import json
import uuid
import time
import io
import requests
from datetime import datetime, timedelta

# ================= 1. INSTALAÇÃO AUTOMÁTICA =================
def install(package):
    try: __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])

install("google-generativeai")
for lib in ["flask", "apscheduler", "python-telegram-bot", "matplotlib", "reportlab", "python-dateutil", "requests"]:
    install(lib)

# ================= 2. IMPORTAÇÕES =================
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from dateutil.relativedelta import relativedelta
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= 3. CONFIGURAÇÃO =================
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ALLOWED_USERS", "0").split(",")[0])
DB_FILE = "finance_v87.json"

# ================= 4. IA SETUP (FOCO EM COTAS ALTAS) =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        # Prioriza o 1.5-flash para garantir 1500 msgs/dia
        model_ai = genai.GenerativeModel('gemini-1.5-flash')
        print("✅ IA David: Conectado ao Gemini 1.5 Flash (1500 msgs/dia)")
    except:
        model_ai = genai.GenerativeModel('gemini-pro')

# ================= 5. BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], "shopping_list": [], "debts_v2": {},
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Casa"]},
        "vip_users": {}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= 6. FUNÇÕES AUXILIARES =================
def get_now(): return datetime.utcnow() - timedelta(hours=3)

def calc_stats():
    gan = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'ganho')
    gas = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto')
    return (gan - gas), gas

def is_vip(uid):
    if uid == ADMIN_ID: return True, "👑 ADMIN"
    u = db["vip_users"].get(str(uid))
    if u and datetime.strptime(u, "%Y-%m-%d") > get_now(): return True, "✅ VIP"
    return False, "❌ Sem VIP"

# ================= 7. INTERFACE PRINCIPAL (BOTÕES VOLTARAM) =================
async def start(update, context):
    uid = update.effective_user.id
    saldo, gastos = calc_stats()
    status, msg_vip = is_vip(uid)
    
    # Botões do Menu (Azuis)
    kb_menu = [
        [InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop"), InlineKeyboardButton("🧾 Dívidas", callback_data="menu_debts")],
        [InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports"), InlineKeyboardButton("📂 Categorias", callback_data="menu_cats")]
    ]
    
    # Botões de Baixo (Teclado fixo)
    kb_reply = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    
    msg = f"💎 **FINANCEIRO V87 - DAVID**\n{msg_vip}\n\n💰 Saldo Total: **R$ {saldo:.2f}**"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_menu), parse_mode="Markdown")
    else:
        # Envia a mensagem com o menu azul E abre o teclado de baixo
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True), parse_mode="Markdown")
        await update.message.reply_text("⚙️ **Opções do Menu:**", reply_markup=InlineKeyboardMarkup(kb_menu))
    return ConversationHandler.END

async def menu_shop(update, context):
    query = update.callback_query; await query.answer()
    l = db["shopping_list"]
    txt = "**🛒 LISTA DE COMPRAS:**\n" + ("_Vazia_" if not l else "\n".join([f"• {i}" for i in l]))
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c"), InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ================= 8. IA HANDLER (COM PROTEÇÃO 429) =================
async def smart_entry(update, context):
    uid = update.effective_user.id
    if not is_vip(uid)[0]: return
    
    msg = update.message; wait = await msg.reply_text("🧠..."); now = get_now()
    
    try:
        prompt = f"AGORA: {now}. Responda APENAS JSON. Mercado: {{'type':'mercado', 'item':'NOME'}}. Finanças: {{'type':'gasto' ou 'ganho', 'val':10.5, 'cat':'Geral'}}"
        content = [prompt, f"User: {msg.text}"]
        
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id); d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": bytes(d)})
            
        resp = model_ai.generate_content(content)
        res_txt = resp.text; data = None
        
        if "{" in res_txt:
            data = json.loads(res_txt[res_txt.find("{"):res_txt.rfind("}")+1])
        
        if data:
            if data.get('type') == 'mercado':
                db["shopping_list"].append(data['item']); save_db(db)
                await wait.edit_text(f"🛒 Adicionado: **{data['item']}**"); return
            if 'val' in data:
                val = float(data['val'])
                db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":data['type'], "value":val, "category":data.get('cat','Geral'), "date":now.strftime("%d/%m/%Y %H:%M")})
                save_db(db); await wait.edit_text(f"✅ Registrado: **R$ {val:.2f}**"); return
        
        await wait.edit_text(res_txt if len(res_txt) < 100 else "Comando processado!")
    except Exception as e:
        if "429" in str(e):
            await wait.edit_text("⚠️ **Limite do Google atingido.**\nAguarde 1 minuto. (Dica: tente mandar texto em vez de áudio/foto)")
        else:
            await wait.edit_text(f"⚠️ Erro IA: {str(e)[:50]}")

# ================= 9. SERVIDOR & MAIN =================
app_flask = Flask('')
@app_flask.route('/')
def home(): return "Bot David Online!"

def run_http():
    try: app_flask.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
    except: pass

if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    app_bot = ApplicationBuilder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(menu_shop, pattern="^menu_shop"))
    app_bot.add_handler(CallbackQueryHandler(start, pattern="^back"))
    app_bot.add_handler(CallbackQueryHandler(lambda u,c: (db.update({"shopping_list":[]}), save_db(db), start(u,c)), pattern="^sl_c"))
    
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, smart_entry))
    
    print("🚀 V87 DAVID RECOVERY NO AR!")
    app_bot.run_polling()
