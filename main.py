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

DB_FILE = "finance_v84.json"

# ESTADOS GLOBAIS
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL, DEBT_ACTION) = range(9)

# ================= 4. SERVIDOR WEB =================
app = Flask('')
@app.route('/')
def home(): return "Bot V84 Online!"

def run_http():
    try: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
    except: pass

def start_keep_alive():
    t = threading.Thread(target=run_http, daemon=True)
    t.start()

# ================= 5. UTILITÁRIOS & DB =================
plt.style.use('dark_background')
COLORS = ['#ff9999','#66b3ff','#99ff99','#ffcc99', '#c2c2f0','#ffb3e6', '#c4e17f']

def get_now(): return datetime.utcnow() - timedelta(hours=3)

def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas"]
        },
        "vip_users": {}, "vip_keys": {}, "wallets": ["Nubank", "Itaú", "Dinheiro"],
        "budgets": {"Alimentação": 1000}, "shopping_list": [], "subscriptions": [], 
        "reminders": [], "debts_v2": {}, 
        "config": {"persona": "padrao", "panic_mode": False, "travel_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            for k in default: 
                if k not in data: data[k] = default[k]
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= 6. IA SETUP (SELETOR AUTOMÁTICO) =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        # Busca automática do melhor modelo disponível
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        chosen = next((m for m in models if 'flash' in m), next((m for m in models if 'pro' in m), 'gemini-pro'))
        model_ai = genai.GenerativeModel(chosen)
        print(f"✅ IA Conectada ao modelo: {chosen}")
    except: model_ai = None

# --- SUPORTE ---
def calc_stats():
    n = get_now(); m = n.strftime("%m/%Y")
    gan = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'ganho')
    gas = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto')
    saldo = gan - gas
    gas_mes = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto' and m in t['date'])
    return saldo, gas_mes

def is_vip(user_id):
    if user_id == ADMIN_ID: return True, "👑 ADMIN"
    uid = str(user_id)
    if uid in db["vip_users"]:
        try:
            if datetime.strptime(db["vip_users"][uid], "%Y-%m-%d") > get_now(): return True, f"✅ VIP"
        except: pass
    return False, "❌ Bloqueado"

def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        if not is_vip(update.effective_user.id)[0]:
            await update.message.reply_text("🚫 VIP Necessário.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ================= 7. FUNÇÕES DE INTERFACE =================

async def start(update, context):
    context.user_data.clear(); saldo, gastos = calc_stats(); uid = update.effective_user.id
    status, msg_vip = is_vip(uid)
    kb_inline = [
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
        [InlineKeyboardButton("🧾 Dívidas/Pessoas", callback_data="menu_debts"), InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🎲 Roleta", callback_data="roleta"), InlineKeyboardButton("⏰ Agenda", callback_data="menu_agenda")],
        [InlineKeyboardButton("⚙️ Configs", callback_data="menu_conf"), InlineKeyboardButton("📚 Manual", callback_data="menu_help")]
    ]
    kb_reply = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    msg = f"💎 **CONTROLE FINANCEIRO V84**\n{msg_vip}\n\n💰 Saldo: **R$ {saldo:.2f}**\n📉 Gastos Mês: R$ {gastos:.2f}"
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_inline), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True), parse_mode="Markdown"); await update.message.reply_text("⚙️ Opções:", reply_markup=InlineKeyboardMarkup(kb_inline))
    return ConversationHandler.END

async def undo_quick(update, context):
    query = update.callback_query; await query.answer()
    if db["transactions"]: db["transactions"].pop(); save_db(db); await query.edit_message_text("🗑️ Desfeito!")
    else: await query.edit_message_text("Nada para desfazer.")

# --- DÍVIDAS ---
async def menu_debts(update, context):
    query = update.callback_query; await query.answer(); debts = db.get("debts_v2", {})
    txt = "🧾 **DÍVIDAS/PESSOAS:**\n\n"; kb = []
    if not debts: txt += "_Ninguém cadastrado._"
    else:
        for name, val in debts.items():
            txt += f"👤 **{name}**: R$ {val:.2f}\n"
            kb.append([InlineKeyboardButton(f"✏️ {name}", callback_data=f"edit_debt_{name}")])
    kb.append([InlineKeyboardButton("➕ Add Pessoa", callback_data="add_person"), InlineKeyboardButton("🔙", callback_data="back")])
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_person_start(update, context):
    await update.callback_query.edit_message_text("Digite o nome da pessoa:"); return DEBT_NAME

async def save_person_name(update, context):
    name = update.message.text
    if name and name not in db["debts_v2"]: db["debts_v2"][name] = 0.0; save_db(db); await update.message.reply_text(f"✅ {name} adicionado(a)!")
    return await start(update, context)

async def edit_debt_menu(update, context):
    name = update.callback_query.data.replace("edit_debt_", ""); context.user_data["debt_name"] = name
    kb = [[InlineKeyboardButton("➕ Emprestei", callback_data="debt_add"), InlineKeyboardButton("➖ Pagou", callback_data="debt_sub")], [InlineKeyboardButton("🗑️ Excluir", callback_data="debt_del"), InlineKeyboardButton("🔙 Voltar", callback_data="menu_debts")]]
    await update.callback_query.edit_message_text(f"👤 {name}", reply_markup=InlineKeyboardMarkup(kb))

async def debt_action(update, context):
    action = update.callback_query.data; name = context.user_data.get("debt_name")
    if action == "debt_del":
        if name in db["debts_v2"]: del db["debts_v2"][name]; save_db(db)
        return await menu_debts(update, context)
    context.user_data["debt_act"] = "add" if action == "debt_add" else "sub"
    await update.callback_query.edit_message_text(f"Qual o valor para {name}?"); return DEBT_VAL

async def debt_save_val(update, context):
    try:
        val = float(update.message.text.replace(',', '.')); name = context.user_data.get("debt_name")
        if context.user_data["debt_act"] == "sub": val = -val
        db["debts_v2"][name] += val; save_db(db)
    except: pass
    return await start(update, context)

# --- MERCADO ---
async def menu_shop(update, context):
    l = db["shopping_list"]; txt = "**🛒 LISTA DE MERCADO:**\n" + ("_Vazio_" if not l else "\n".join([f"• {i}" for i in l]))
    kb = [[InlineKeyboardButton("🗑️ Limpar Lista", callback_data="sl_c"), InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def sl_c(update, context): db["shopping_list"] = []; save_db(db); await start(update, context)

# --- MANUAL REG ---
async def manual_reg_trigger(update, context):
    context.user_data["t"] = "gasto" if "Gasto" in update.message.text else "ganho"
    await update.message.reply_text("💰 Qual o valor? (Ex: 50.90)"); return REG_VALUE

async def reg_val(update, context):
    try:
        context.user_data["v"] = float(update.message.text.replace(',', '.'))
        cats = db["categories"][context.user_data["t"]]
    except: return REG_VALUE
    kb = [[InlineKeyboardButton(c, callback_data=f"sc_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await update.message.reply_text("Selecione a Categoria:", reply_markup=InlineKeyboardMarkup(kb)); return REG_CAT

async def reg_cat(update, context):
    context.user_data["c"] = update.callback_query.data.replace("sc_", "")
    await update.callback_query.edit_message_text("Descrição (ou mande /pular):"); return REG_DESC

async def reg_fin(update, context):
    desc = update.message.text if update.message and update.message.text != "/pular" else context.user_data["c"]
    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":context.user_data["t"], "value":context.user_data["v"], "category":context.user_data["c"], "description":desc, "date":get_now().strftime("%d/%m/%Y %H:%M")})
    save_db(db); await (update.message or update.callback_query.message).reply_text("✅ Salvo com sucesso!"); return await start(update, context)

# ================= 8. IA HANDLER (ADAPTATIVO V84) =================

@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message; wait = await msg.reply_text("🧠 Processando..."); now = get_now()
    try:
        # Prompt Ultra-Flexível
        prompt = f"""SISTEMA: Vc é assistente financeiro. AGORA: {now}. 
        VC DEVE RESPONDER APENAS EM JSON.
        TAREFAS: 
        1. REGISTRO: {{"type":"gasto" ou "ganho", "value":X, "category":"str", "description":"str"}}
        2. MERCADO: {{"type":"mercado", "item":"str"}}
        3. CONSULTA/OUTROS: Texto amigável.
        
        Se o user disser "comprar leite" ou "põe pão na lista", use type:mercado.
        """
        
        content = [prompt]
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id); d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": bytes(d)})
        elif msg.voice:
            # O Flash aceita voz, o Pro clássico não. Vamos mandar texto como fallback.
            content.append("Entrada de áudio recebida.")
        else:
            content.append(f"Usuário diz: {msg.text}")
            
        resp = model_ai.generate_content(content)
        t = resp.text; data = None
        
        # Extrator de JSON flexível
        if "{" in t:
            try: 
                clean_json = t[t.find("{"):t.rfind("}")+1]
                data = json.loads(clean_json)
            except: pass
        
        if data:
            # Normalização de Chaves (Português/Inglês)
            task_type = data.get('type') or data.get('tarefa')
            if task_type: task_type = task_type.lower()

            if task_type in ['mercado', 'shopping']:
                item = data.get('item') or data.get('produto')
                if item:
                    db["shopping_list"].append(item); save_db(db)
                    await wait.edit_text(f"🛒 **Adicionado ao Mercado:** {item}"); return

            if 'value' in data or 'valor' in data:
                val = float(data.get('value') or data.get('valor'))
                tp = (data.get('type') or data.get('tipo') or 'gasto').lower()
                cat = data.get('category') or data.get('categoria') or 'Geral'
                desc = data.get('description') or data.get('descricao') or 'IA'
                db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":tp, "value":val, "category":cat, "description":desc, "date":now.strftime("%d/%m/%Y %H:%M")})
                save_db(db); await wait.edit_text(f"✅ **Registrado:** R$ {val:.2f} ({cat})"); return
        
        await wait.edit_text(t)
    except Exception as e: await wait.edit_text(f"⚠️ Erro no Cérebro: {e}")

# ================= 9. MAIN =================
def main():
    print("🚀 Iniciando Bot V84...")
    start_keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers de Conversa
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^(💸 Gasto|💰 Ganho)$"), manual_reg_trigger)],
        states={REG_VALUE:[MessageHandler(filters.TEXT & ~filters.COMMAND, reg_val)], REG_CAT:[CallbackQueryHandler(reg_cat)], REG_DESC:[MessageHandler(filters.TEXT | filters.COMMAND, reg_fin)]},
        fallbacks=[CommandHandler("start", start)], per_message=True
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_person")],
        states={DEBT_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, save_person_name)], DEBT_VAL:[MessageHandler(filters.TEXT & ~filters.COMMAND, debt_save_val)]},
        fallbacks=[CommandHandler("start", start)], per_message=True
    ))
    
    # Comandos e Callbacks
    app.add_handler(CommandHandler("start", start))
    cbs = [("menu_shop", menu_shop), ("sl_c", sl_c), ("menu_debts", menu_debts), ("edit_debt_", edit_debt_menu), ("debt_", debt_action), ("undo_quick", undo_quick), ("back", start)]
    for p, f in cbs: app.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, smart_entry))
    
    print("✅ SISTEMA V84 OPERANTE!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
