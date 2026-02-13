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

# ================= 1. AUTO-INSTALAÇÃO =================
def install(package):
    try: __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

required = ["flask", "apscheduler", "telegram", "google.generativeai", "matplotlib", "reportlab", "python-dateutil", "requests"]
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

# ================= 3. CONFIGURAÇÃO =================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

try:
    users_env = os.getenv("ALLOWED_USERS", "0")
    ADMIN_ID = int(users_env.split(",")[0]) if "," in users_env else int(users_env)
except: ADMIN_ID = 0

DB_FILE = "finance_v85.json"
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL, DEBT_ACTION) = range(9)

# ================= 4. SERVIDOR WEB =================
app = Flask('')
@app.route('/')
def home(): return "Bot V85 Online!"
def run_http():
    try: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
    except: pass
def start_keep_alive(): threading.Thread(target=run_http, daemon=True).start()

# ================= 5. DB & UTILS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa"]},
        "vip_users": {}, "vip_keys": {}, "shopping_list": [], "reminders": [], "debts_v2": {}, 
        "config": {"persona": "padrao", "panic_mode": False, "travel_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= 6. IA SETUP (V85 - MODELO ESTÁVEL) =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        # Forçamos o 1.5-flash que tem limite de 1500 requests/dia no free
        model_ai = genai.GenerativeModel('gemini-1.5-flash')
        print("✅ IA Conectada: gemini-1.5-flash (Limite 1500/dia)")
    except:
        model_ai = genai.GenerativeModel('gemini-pro')

# --- LOGICA FINANCEIRA ---
def calc_stats():
    gan = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'ganho')
    gas = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto')
    return (gan - gas), gas

def is_vip(uid):
    if uid == ADMIN_ID: return True, "👑 ADMIN"
    u = db["vip_users"].get(str(uid))
    if u and datetime.strptime(u, "%Y-%m-%d") > (datetime.utcnow() - timedelta(hours=3)): return True, "✅ VIP"
    return False, "❌ Bloqueado"

# ================= 7. INTERFACE =================

async def start(update, context):
    context.user_data.clear(); saldo, gastos = calc_stats(); status, msg_vip = is_vip(update.effective_user.id)
    kb = [[InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
          [InlineKeyboardButton("🧾 Dívidas", callback_data="menu_debts"), InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports")],
          [InlineKeyboardButton("📚 Manual", callback_data="menu_help")]]
    msg = f"💎 **FINANCEIRO V85**\n{msg_vip}\n\n💰 Saldo: **R$ {saldo:.2f}**"
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup([["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]], resize_keyboard=True), parse_mode="Markdown")
    return ConversationHandler.END

# --- DÍVIDAS ---
async def menu_debts(update, context):
    debts = db.get("debts_v2", {}); txt = "🧾 **DÍVIDAS:**\n"; kb = []
    for n, v in debts.items(): kb.append([InlineKeyboardButton(f"✏️ {n}: R$ {v:.2f}", callback_data=f"ed_{n}")])
    kb.append([InlineKeyboardButton("➕ Add Pessoa", callback_data="add_p"), InlineKeyboardButton("🔙", callback_data="back")])
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_p(update, context): await update.callback_query.edit_message_text("Nome:"); return DEBT_NAME
async def save_p(update, context):
    n = update.message.text; db["debts_v2"][n] = 0.0; save_db(db); await update.message.reply_text(f"✅ {n} salvo!")
    return await start(update, context)

# --- MERCADO ---
async def menu_shop(update, context):
    l = db["shopping_list"]; txt = "**🛒 MERCADO:**\n" + ("_Vazio_" if not l else "\n".join([f"• {i}" for i in l]))
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c"), InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ================= 8. IA HANDLER (ADAPTATIVO V85) =================

async def smart_entry(update, context):
    uid = update.effective_user.id
    if not is_vip(uid)[0]: await update.message.reply_text("🚫 VIP necessário."); return
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    
    msg = update.message; txt = msg.text; wait = await msg.reply_text("🧠..."); now = (datetime.utcnow() - timedelta(hours=3))
    
    try:
        prompt = f"""AGORA: {now}. Responda APENAS em JSON. 
        Se o usuário quiser:
        - Registrar gasto/ganho: {{"type":"gasto", "val":10.5, "cat":"Lazer"}}
        - Mercado (ex: 'comprar leite'): {{"type":"mercado", "item":"leite"}}
        - Outros: {{"type":"conversa", "msg":"texto"}}"""
        
        content = [prompt, f"User: {txt}"]
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
                await wait.edit_text(f"🛒 **Mercado:** {data['item']} adicionado!"); return
            if 'val' in data:
                db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":data['type'], "value":float(data['val']), "category":data.get('cat','Geral'), "date":now.strftime("%d/%m/%Y %H:%M")})
                save_db(db); await wait.edit_text(f"✅ Registrado: R$ {data['val']:.2f}"); return
        
        await wait.edit_text(res_txt if len(res_txt) < 100 else "Entendido!")
        
    except Exception as e:
        if "429" in str(e):
            await wait.edit_text("⚠️ **Limite do Google atingido.**\nEspere 1 minuto e tente novamente.")
        else:
            await wait.edit_text(f"⚠️ Erro: {e}")

# ================= 9. MAIN =================
def main():
    start_keep_alive()
    app_bot = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_p, pattern="^add_p")],
        states={DEBT_NAME:[MessageHandler(filters.TEXT, save_p)]},
        fallbacks=[CommandHandler("start", start)], per_message=True
    ))
    
    cbs = [("menu_shop", menu_shop), ("menu_debts", menu_debts), ("back", start), ("sl_c", lambda u,c: (db.update({"shopping_list":[]}), save_db(db), start(u,c)))]
    for p, f in cbs: app_bot.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, smart_entry))
    
    print("🚀 V85 RODANDO!")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
