import os
import sys
import subprocess
import logging
import threading
import json
import uuid
import time
import io
import math
import random
from datetime import datetime, timedelta

# ================= 1. AUTO-INSTALAÇÃO SEGURA =================
def install(package):
    try: __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])

# Força a versão mais nova para evitar o erro 404
install("google-generativeai")
required = ["flask", "apscheduler", "python-telegram-bot", "matplotlib", "reportlab", "python-dateutil", "requests"]
for lib in required: install(lib)

# ================= 2. IMPORTAÇÕES =================
from flask import Flask
import requests
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

# ================= 3. CONFIGURAÇÃO GERAL =================
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

try:
    users_env = os.getenv("ALLOWED_USERS", "0")
    ADMIN_ID = int(users_env.split(",")[0]) if "," in users_env else int(users_env)
except: ADMIN_ID = 0

DB_FILE = "finance_v86.json"
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL) = range(8)

# ================= 4. IA SETUP (DINÂMICO ANTI-404) =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        # Busca modelos reais disponíveis na sua conta
        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # Prioridade: 1.5-flash (Limite alto), depois 1.5-pro, depois gemini-pro
        if any('1.5-flash' in m for m in available):
            chosen = next(m for m in available if '1.5-flash' in m)
        elif any('gemini-pro' in m for m in available):
            chosen = next(m for m in available if 'gemini-pro' in m)
        else:
            chosen = available[0]
        
        model_ai = genai.GenerativeModel(chosen)
        print(f"✅ IA Conectada ao modelo oficial: {chosen}")
    except Exception as e:
        print(f"⚠️ Erro ao listar modelos, usando fallback: {e}")
        model_ai = genai.GenerativeModel('gemini-pro')

# ================= 5. BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], "shopping_list": [], "debts_v2": {},
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Casa"]},
        "vip_users": {}, "config": {"panic_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= 6. FUNÇÕES DE APOIO =================
def get_now(): return datetime.utcnow() - timedelta(hours=3)

def calc_stats():
    gan = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'ganho')
    gas = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto')
    return (gan - gas), gas

def is_vip(uid):
    if uid == ADMIN_ID: return True, "👑 ADMIN"
    u = db["vip_users"].get(str(uid))
    if u and datetime.strptime(u, "%Y-%m-%d") > get_now(): return True, "✅ VIP"
    return False, "❌ Bloqueado"

# ================= 7. INTERFACE (START/MENUS) =================
async def start(update, context):
    saldo, gastos = calc_stats()
    status, msg_vip = is_vip(update.effective_user.id)
    kb = [[InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop"), InlineKeyboardButton("🧾 Dívidas", callback_data="menu_debts")],
          [InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports"), InlineKeyboardButton("📂 Categorias", callback_data="menu_cats")]]
    
    msg = f"💎 **FINANCEIRO V86**\n{msg_vip}\n\n💰 Saldo: **R$ {saldo:.2f}**"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        reply_kb = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(reply_kb, resize_keyboard=True), parse_mode="Markdown")
    return ConversationHandler.END

async def menu_shop(update, context):
    l = db["shopping_list"]
    txt = "**🛒 LISTA DE MERCADO:**\n" + ("_Vazia_" if not l else "\n".join([f"• {i}" for i in l]))
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c"), InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ================= 8. IA HANDLER (MERCADO + FINANÇAS) =================
async def smart_entry(update, context):
    if not is_vip(update.effective_user.id)[0]: return
    msg = update.message; wait = await msg.reply_text("🧠..."); now = get_now()
    
    try:
        prompt = f"AGORA: {now}. Responda APENAS JSON. Se for mercado (ex: 'comprar carne'): {{'type':'mercado', 'item':'carne'}}. Se for gasto/ganho: {{'type':'gasto', 'val':10.5, 'cat':'Lazer'}}"
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
                await wait.edit_text(f"🛒 Adicionado ao Mercado: **{data['item']}**"); return
            if 'val' in data:
                val = float(data['val'])
                db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":data['type'], "value":val, "category":data.get('cat','Geral'), "date":now.strftime("%d/%m/%Y %H:%M")})
                save_db(db); await wait.edit_text(f"✅ Registrado: **R$ {val:.2f}**"); return
        
        await wait.edit_text("Não entendi o comando. Tente: 'Gastei 50 com pizza' ou 'Comprar leite'.")
    except Exception as e:
        await wait.edit_text(f"⚠️ Erro: {str(e)[:50]}")

# ================= 9. SERVIDOR KEEP ALIVE =================
app_flask = Flask('')
@app_flask.route('/')
def home(): return "Bot Online!"

def run_http():
    try: app_flask.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
    except: pass

# ================= 10. MAIN =================
if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    app_bot = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers Simples
    app_bot.add_handler(CommandHandler("start", start))
    
    # Callbacks
    app_bot.add_handler(CallbackQueryHandler(menu_shop, pattern="^menu_shop"))
    app_bot.add_handler(CallbackQueryHandler(start, pattern="^back"))
    app_bot.add_handler(CallbackQueryHandler(lambda u,c: (db.update({"shopping_list":[]}), save_db(db), start(u,c)), pattern="^sl_c"))
    
    # Mensagens de texto/foto/áudio
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, smart_entry))
    
    print("🚀 V86 IRONCLAD NO AR!")
    app_bot.run_polling()
