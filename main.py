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
import requests
from datetime import datetime, timedelta

# ================= AUTO-CORREÇÃO =================
def install_package(package):
    try: subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except: pass

try: from flask import Flask
except ImportError: install_package("flask"); from flask import Flask

try: from apscheduler.schedulers.background import BackgroundScheduler
except ImportError: install_package("apscheduler"); from apscheduler.schedulers.background import BackgroundScheduler

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from dateutil.relativedelta import relativedelta
    import google.generativeai as genai
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    install_package("python-telegram-bot"); install_package("google-generativeai>=0.7.0")
    install_package("matplotlib"); install_package("reportlab"); install_package("python-dateutil")
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from dateutil.relativedelta import relativedelta
    import google.generativeai as genai
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

try:
    users_env = os.getenv("ALLOWED_USERS", "0")
    ADMIN_ID = int(users_env.split(",")[0]) if "," in users_env else int(users_env)
except: ADMIN_ID = 0

DB_FILE = "finance_v59_stable.json"

# ================= KEEP ALIVE =================
app = Flask('')
@app.route('/')
def home(): return "Bot V59 (Stable) Online!"
def run_http():
    try: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", "10000")))
    except: pass
def start_keep_alive(): threading.Thread(target=run_http, daemon=True).start()

# ================= VISUAL =================
plt.style.use('dark_background')
COLORS = ['#ff9999','#66b3ff','#99ff99','#ffcc99', '#c2c2f0','#ffb3e6', '#c4e17f']
def get_now(): return datetime.utcnow() - timedelta(hours=3)

# ================= MARKET DATA =================
def get_market_data():
    try:
        r = requests.get("https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL", timeout=5)
        d = r.json()
        usd = float(d['USDBRL']['bid'])
        eur = float(d['EURBRL']['bid'])
        return {"usd": usd, "eur": eur, "txt": f"Dólar: {usd:.2f} | Euro: {eur:.2f}"}
    except:
        return {"usd": 5.80, "eur": 6.20, "txt": "API Offline (Ref: 5.80)"}

# ================= IA =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        chosen = next((m for m in models if 'flash' in m), next((m for m in models if 'gemini-pro' in m), None))
        model_ai = genai.GenerativeModel(chosen if chosen else 'gemini-pro')
    except: 
        try: model_ai = genai.GenerativeModel('gemini-pro')
        except: model_ai = None

# ================= DB =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas"]
        },
        "vip_users": {}, "vip_keys": {},
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Crédito"],
        "budgets": {"Alimentação": 1000},
        "shopping_list": [], "subscriptions": [], 
        "reminders": [],
        "debts_v2": {}, 
        "user_level": {"xp": 0, "title": "Iniciante 🌱"},
        "config": {"persona": "padrao", "panic_mode": False, "travel_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            if "debts_v2" not in data: data["debts_v2"] = {}
            for k in default: 
                if k not in data: data[k] = default[k]
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= SCHEDULER =================
async def check_reminders(context):
    now_str = get_now().strftime("%Y-%m-%d %H:%M")
    to_remove = []
    
    if "reminders" in db and db["reminders"]:
        for i, rem in enumerate(db["reminders"]):
            if rem["time"] == now_str:
                try:
                    await context.bot.send_message(chat_id=rem["chat_id"], text=f"⏰ **LEMBRETE!**\n\n📌 {rem['text']}", parse_mode="Markdown")
                    to_remove.append(i)
                except: pass
        
        if to_remove:
            for index in sorted(to_remove, reverse=True):
                del db["reminders"][index]
            save_db(db)

# ================= VIP =================
def is_vip(user_id):
    if user_id == ADMIN_ID: return True, "👑 ADMIN"
    uid = str(user_id)
    if uid in db["vip_users"]:
        try:
            if datetime.strptime(db["vip_users"][uid], "%Y-%m-%d") > get_now():
                dias = (datetime.strptime(db["vip_users"][uid], "%Y-%m-%d") - get_now()).days
                return True, f"✅ VIP ({dias}d)"
        except: pass
    return False, "❌ Bloqueado"

def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        status, msg = is_vip(user_id)
        if not status:
            kb = [[InlineKeyboardButton("🔑 Chave", callback_data="input_key")]]
            await update.message.reply_text(f"🚫 **BLOQUEADO**\nCompre sua chave VIP.", reply_markup=InlineKeyboardMarkup(kb))
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ================= ADMIN =================
async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_ID: return
    query = update.callback_query; 
    if query: await query.answer()
    uc = len(db["vip_users"]); kc = len([k for k, v in db["vip_keys"].items() if not v['used']])
    txt = f"👑 **PAINEL**\n👥: {uc} | 🔑: {kc}"
    kb = [[InlineKeyboardButton("📅 30 Dias", callback_data="gen_30"), InlineKeyboardButton("📅 90 Dias", callback_data="gen_90")],
          [InlineKeyboardButton("📅 7 Dias", callback_data="gen_7"), InlineKeyboardButton("♾️ 1 Ano", callback_data="gen_365")],
          [InlineKeyboardButton("🔙", callback_data="back")]]
    if query: await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def gen_key(update, context):
    if update.effective_user.id != ADMIN_ID: return
    query = update.callback_query; await query.answer()
    days = int(query.data.replace("gen_", ""))
    key = f"VIP-{uuid.uuid4().hex[:6].upper()}"
    db["vip_keys"][key] = {"days": days, "used": False}; save_db(db)
    await query.message.reply_text(f"✅ `{key}` ({days}d)", parse_mode="Markdown")
    await admin_panel(update, context)

async def ask_key(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Use: `/resgatar CODIGO`")

async def redeem_key(update, context):
    uid = str(update.effective_user.id)
    try: key = context.args[0].strip()
    except: await update.message.reply_text("❌ `/resgatar CHAVE`"); return
    kd = db["vip_keys"].get(key)
    if not kd or kd["used"]: await update.message.reply_text("❌ Inválido."); return
    curr = db["vip_users"].get(uid)
    base = datetime.strptime(curr, "%Y-%m-%d") if curr and datetime.strptime(curr, "%Y-%m-%d") > get_now() else get_now()
    new_d = base + timedelta(days=kd["days"])
    db["vip_users"][uid] = new_d.strftime("%Y-%m-%d"); db["vip_keys"][key]["used"] = True; save_db(db)
    await update.message.reply_text(f"🎉 VIP até {new_d.strftime('%d/%m/%Y')}\n/start", parse_mode="Markdown")

# ================= UTILS =================
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL, DEBT_ACTION) = range(9)

def calc_stats():
    n = get_now(); m = n.strftime("%m/%Y")
    gan = sum(t['value'] for t in db["transactions"] if t['type']=='ganho' and m in t['date'])
    gas = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])
    return (gan-gas), gan, gas

def check_budget(cat, val):
    lim = db["budgets"].get(cat, 0); m = get_now().strftime("%m/%Y")
    if lim == 0: return None
    curr = sum(t['value'] for t in db["transactions"] if t['category']==cat and t['type']=='gasto' and m in t['date'])
    if (curr+val) > lim: return f"🚨 Teto de {cat}!"
    return None

# ================= IA =================
class MockQuery:
    def __init__(self, data, msg): self.data = data; self.message = msg
    async def answer(self, *args, **kwargs): pass
    async def edit_message_text(self, text, reply_markup=None, **kwargs): await self.message.reply_text(text, reply_markup=reply_markup)

@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message
    txt = msg.text
    
    if txt == "💸 Gasto": update.callback_query = MockQuery('reg_gasto', msg); return await reg_type(update, context)
    if txt == "💰 Ganho": update.callback_query = MockQuery('reg_ganho', msg); return await reg_type(update, context)
    if txt == "📊 Relatórios": return await menu_reports_trigger(update, context)
    if txt == "👛 Saldo": return await start(update, context)

    if msg.document and msg.document.file_name.endswith(".json"):
        f = await context.bot.get_file(msg.document.file_id); await f.download_to_drive(DB_FILE)
        global db; 
        with open(DB_FILE, "r") as fl: db = json.load(fl)
        await msg.reply_text("✅ Backup Restaurado!"); return

    travel = db["config"]["travel_mode"]; panic = db["config"]["panic_mode"]
    role = {"julius":"Julius Rock", "primo":"Primo Rico", "mae":"Mãe", "zoeiro":"Zoeiro", "padrao":"Assistente"}.get(db["config"]["persona"], "Assistente")

    if panic and txt and any(b in txt.lower() for b in ["lazer","cerveja","pizza","bar","ifood"]):
        await msg.reply_text("🛑 PÂNICO ATIVO!"); return

    wait = await msg.reply_text("🎤..." if (msg.voice or msg.audio) else "🧠...")
    mkt = get_market_data()
    now_user = get_now().strftime("%Y-%m-%d %H:%M")
    
    try:
        content = []; 
        prompt = f"""
        SISTEMA: Você é {role}. AGORA (Brasília): {now_user}.
        COTAÇÃO: Dólar={mkt['usd']}, Euro={mkt['eur']}.
        VIAGEM: {'ON' if travel else 'OFF'}.

        TAREFAS:
        1. LEMBRETE: Se user pedir "lembrar x dia y as z horas", gere JSON: {{"type":"lembrete", "text":"descricao", "time":"YYYY-MM-DD HH:MM"}}.
           *Importante: Use o ano atual ou seguinte. Formato 24h.*
        2. GASTO/GANHO: Se for finanças, gere JSON: {{"type":"gasto/ganho","value":float_brl,"category":"str","description":"str","installments":1,"comment":"str"}}.
        3. CONVERSA: Texto.
        """
        content.append(prompt)
        file_path = None
        
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id); d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": d})
        elif msg.voice or msg.audio:
            fid = (msg.voice or msg.audio).file_id; f = await context.bot.get_file(fid)
            ext = ".ogg" if msg.voice else ".mp3"; file_path = f"aud_{uuid.uuid4()}{ext}"
            await f.download_to_drive(file_path)
            try:
                up = genai.upload_file(file_path)
                while up.state.name == "PROCESSING": time.sleep(1)
                content.append(up)
            except: 
                if os.path.exists(file_path): os.remove(file_path)
                await wait.edit_text("Erro upload."); return
        else: content.append(f"Input: {txt}")
            
        resp = model_ai.generate_content(content)
        t = resp.text.strip().replace("```json", "").replace("```", "")
        if file_path and os.path.exists(file_path): os.remove(file_path)
        
        data = None
        if "{" in t:
            try: data = json.loads(t[t.find("{"):t.rfind("}")+1])
            except: 
                try: data = ast.literal_eval(t[t.find("{"):t.rfind("}")+1])
                except: pass
        
        if data:
            if data.get('type') == 'lembrete':
                if "reminders" not in db: db["reminders"] = []
                db["reminders"].append({"text": data['text'], "time": data['time'], "chat_id": update.effective_chat.id})
                save_db(db)
                await wait.edit_text(f"⏰ **Agendado!**\n\n📌 {data['text']}\n📅 {data['time']}")
                return

            if data['type']=='gasto' and check_budget(data['category'], float(data['value'])) and panic: await wait.edit_text("🛑 Teto!"); return
            inst = data.get("installments", 1); val = float(data['value'])
            for i in range(inst):
                dt = get_now() + relativedelta(months=i); desc = data['description']
                if inst > 1: desc += f" ({i+1}/{inst})"
                tr = {"id":str(uuid.uuid4())[:8], "type":data['type'], "value":val/inst if inst>1 else val, "category":data['category'], "description":desc, "date":dt.strftime("%d/%m/%Y %H:%M")}
                db["transactions"].append(tr)
            
            save_db(db); context.user_data["last_id"] = tr["id"]
            
            msg_ok = f"✅ **R$ {val:.2f}** | {data['category']}\n📝 {data['description']}"
            if inst>1: msg_ok += f"\n📅 {inst}x"
            if data.get('comment'): msg_ok += f"\n\n🗣️ {data['comment']}"
            if travel and "dolar" in txt.lower(): msg_ok += f"\n(Conv: USD {mkt['usd']:.2f})"
            
            kb = [[InlineKeyboardButton("↩️ Desfazer", callback_data="undo_quick")]]
            await wait.edit_text(msg_ok, reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text(t)
            
    except Exception as e: await wait.edit_text(f"⚠️ Erro: {e}")

async def undo_quick(update, context):
    query = update.callback_query; await query.answer(); lid = context.user_data.get("last_id")
    if lid: db["transactions"] = [t for t in db["transactions"] if t['id'] != lid]; save_db(db); await query.edit_message_text("🗑️ Desfeito!")
    else: await query.edit_message_text("Nada para desfazer.")

# ================= MENU =================
@restricted
async def start(update, context):
    context.user_data.clear(); saldo, ganho, gasto = calc_stats(); uid = update.effective_user.id; vip_ok, vip_msg = is_vip(uid)
    ind_panic = "🛑 PÂNICO" if db["config"]["panic_mode"] else ""
    ind_travel = "✈️ VIAGEM" if db["config"]["travel_mode"] else ""
    st = f"{ind_panic} {ind_travel}".strip()
    
    kb_inline = [
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
        [InlineKeyboardButton("🧾 Dívidas/Pessoas", callback_data="menu_debts"), InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🎲 Roleta", callback_data="roleta"), InlineKeyboardButton("⏰ Agenda", callback_data="menu_agenda")],
        [InlineKeyboardButton("⚙️ Configs", callback_data="menu_conf"), InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]
    if uid == ADMIN_ID: kb_inline.insert(0, [InlineKeyboardButton("👑 PAINEL DO DONO", callback_data="admin_panel")])
    kb_reply = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    
    msg = f"💎 **FINANCEIRO V59**\n{vip_msg}\n{st}\n\n💰 Saldo: **R$ {saldo:.2f}**\n📉 Gastos: R$ {gasto:.2f}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_inline), parse_mode="Markdown")
        try: m = await context.bot.send_message(chat_id=update.effective_chat.id, text="...", reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True)); await m.delete()
        except: pass
    else:
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True), parse_mode="Markdown")
        await update.message.reply_text("⚙️ **Menu:**", reply_markup=InlineKeyboardMarkup(kb_inline))
    return ConversationHandler.END

async def back(update, context): 
    if update.callback_query: await update.callback_query.answer()
    await start(update, context)

# ================= DÍVIDAS POR PESSOA =================
async def menu_debts(update, context):
    query = update.callback_query; await query.answer()
    debts = db.get("debts_v2", {})
    txt = "🧾 **CONTROLE DE PESSOAS**\n\n"
    kb = []
    if not debts: txt += "_Ninguém cadastrado._"
    else:
        for name, val in debts.items():
            sinal = "🔴 Deve" if val > 0 else "🟢 Crédito"
            txt += f"👤 **{name}**: {sinal} R$ {abs(val):.2f}\n"
            kb.append([InlineKeyboardButton(f"✏️ {name}", callback_data=f"edit_debt_{name}")])
    kb.append([InlineKeyboardButton("➕ Adicionar Pessoa", callback_data="add_person")])
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="back")])
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_person_start(update, context):
    await update.callback_query.edit_message_text("Digite o nome da pessoa:")
    return DEBT_NAME

async def save_person_name(update, context):
    name = update.message.text
    if name not in db["debts_v2"]: db["debts_v2"][name] = 0.0; save_db(db); await update.message.reply_text(f"✅ {name} adicionado(a)!")
    else: await update.message.reply_text("⚠️ Já existe.")
    return await start(update, context)

async def edit_debt_menu(update, context):
    name = update.callback_query.data.replace("edit_debt_", "")
    context.user_data["debt_name"] = name
    val = db["debts_v2"].get(name, 0)
    txt = f"👤 **{name}**\nSaldo atual: R$ {val:.2f}\n\nO que deseja fazer?"
    kb = [[InlineKeyboardButton("➕ Emprestei (Aumentar)", callback_data="debt_add"), InlineKeyboardButton("➖ Pagou (Diminuir)", callback_data="debt_sub")],
          [InlineKeyboardButton("🗑️ Excluir Pessoa", callback_data="debt_del"), InlineKeyboardButton("🔙 Voltar", callback_data="menu_debts")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def debt_action(update, context):
    action = update.callback_query.data
    name = context.user_data["debt_name"]
    if action == "debt_del":
        del db["debts_v2"][name]; save_db(db); await update.callback_query.answer("Apagado!"); return await menu_debts(update, context)
    context.user_data["debt_act"] = "add" if action == "debt_add" else "sub"
    await update.callback_query.edit_message_text(f"Qual valor para {name}?")
    return DEBT_VAL

async def debt_save_val(update, context):
    try:
        val = float(update.message.text.replace(',', '.'))
        name = context.user_data["debt_name"]
        if context.user_data["debt_act"] == "sub": val = -val
        db["debts_v2"][name] += val; save_db(db)
        await update.message.reply_text(f"✅ Atualizado! Novo saldo de {name}: R$ {db['debts_v2'][name]:.2f}")
    except: await update.message.reply_text("❌ Valor inválido.")
    return await start(update, context)

# ================= AGENDA =================
async def menu_agenda(update, context):
    query = update.callback_query; await query.answer()
    rems = db.get("reminders", [])
    if not rems: await query.edit_message_text("📭 Sem lembretes.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]])); return
    txt = "⏰ **AGENDA DE LEMBRETES:**\n\n"
    kb = []; rems.sort(key=lambda x: x['time'])
    for i, r in enumerate(rems):
        txt += f"📅 {r['time']} - {r['text']}\n"
        kb.append([InlineKeyboardButton(f"🗑️ Apagar {r['time'].split(' ')[1]}", callback_data=f"del_agenda_{i}")])
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="back")])
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def agenda_del(update, context):
    query = update.callback_query
    try:
        idx = int(query.data.replace("del_agenda_", ""))
        if 0 <= idx < len(db["reminders"]):
            removed = db["reminders"].pop(idx); save_db(db)
            await query.answer(f"🗑️ Lembrete apagado!"); await menu_agenda(update, context)
        else: await query.answer("Erro.")
    except: await query.answer("Erro.")

# ================= OUTROS MENUS =================
async def menu_conf(update, context):
    p = "🔴 ON" if db["config"]["panic_mode"] else "🟢 OFF"
    t = "✈️ ON" if db["config"]["travel_mode"] else "🏠 OFF"
    kb = [[InlineKeyboardButton(f"Pânico: {p}", callback_data="tg_panic"), InlineKeyboardButton(f"Viagem: {t}", callback_data="tg_travel")],
          [InlineKeyboardButton("🎭 Persona", callback_data="menu_persona"), InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    if update.callback_query.message.text.startswith("⚙️"): await update.callback_query.edit_message_text("⚙️ **Configurações:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.callback_query.edit_message_text("⚙️ **Configurações:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def tg_panic(update, context): db["config"]["panic_mode"] = not db["config"]["panic_mode"]; save_db(db); await menu_conf(update, context)
async def tg_travel(update, context): db["config"]["travel_mode"] = not db["config"]["travel_mode"]; save_db(db); await menu_conf(update, context)

async def menu_reports_trigger(update, context):
    kb = [[InlineKeyboardButton("📝 Extrato", callback_data="rep_list"), InlineKeyboardButton("🍕 Pizza", callback_data="rep_pie")],
          [InlineKeyboardButton("📊 CSV", callback_data="rep_csv"), InlineKeyboardButton("📄 PDF", callback_data="rep_pdf")],
          [InlineKeyboardButton("📅 Mapa", callback_data="rep_nospend"), InlineKeyboardButton("📉 Evolução", callback_data="rep_evo")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    await update.message.reply_text("📊 **Relatórios Completos:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_reports(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📝 Extrato", callback_data="rep_list"), InlineKeyboardButton("🍕 Pizza", callback_data="rep_pie")],
          [InlineKeyboardButton("📊 CSV", callback_data="rep_csv"), InlineKeyboardButton("📄 PDF", callback_data="rep_pdf")],
          [InlineKeyboardButton("📅 Mapa", callback_data="rep_nospend"), InlineKeyboardButton("📉 Evolução", callback_data="rep_evo")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    await query.edit_message_text("📊 **Relatórios Completos:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def rep_list(update, context):
    query = update.callback_query; await query.answer()
    trans = db["transactions"][-15:]
    if not trans: await query.edit_message_text("📭 Vazio.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]])); return
    txt = "📝 **Últimos 15:**\n\n"
    for t in reversed(trans): txt += f"{'🔴' if t['type']=='gasto' else '🟢'} {t['date']} | R$ {t['value']:.2f}\n🏷️ {t['category']} - {t['description']}\n\n"
    await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

async def rep_pie(update, context):
    query = update.callback_query; await query.answer()
    cats = {}; m = get_now().strftime("%m/%Y")
    for t in db["transactions"]:
        if t['type']=='gasto' and m in t['date']: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    if not cats: await query.edit_message_text("Sem dados.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]])); return
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.pie(cats.values(), autopct='%1.1f%%', startangle=90, colors=COLORS)
    ax.legend(cats.keys(), loc="best", bbox_to_anchor=(1, 0.5)); ax.set_title(f"Gastos {m}", color='white')
    buf = io.BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)

async def rep_pdf(update, context):
    query = update.callback_query; await query.answer()
    c = canvas.Canvas("relatorio.pdf", pagesize=letter)
    c.drawString(50, 750, "EXTRATO FINANCEIRO VIP")
    c.drawString(50, 730, "-"*60); y = 700
    for t in reversed(db["transactions"][-40:]):
        if y < 50: break
        c.drawString(50, y, f"{t['date']} | {t['type'].upper()} | R$ {t['value']:.2f} | {t['category']} | {t['description']}")
        y -= 15
    c.save()
    with open("relatorio.pdf", "rb") as f: await query.message.reply_document(f)

async def rep_csv(update, context):
    query = update.callback_query; await query.answer()
    with open("relatorio.csv", "w", newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(["Data", "Tipo", "Valor", "Categoria", "Descricao"])
        for t in db["transactions"]: w.writerow([t['date'], t['type'], str(t['value']).replace('.',','), t['category'], t['description']])
    with open("relatorio.csv", "rb") as f: await query.message.reply_document(f)

async def rep_evo(update, context):
    query = update.callback_query; await query.answer(); d, l = [], []
    for i in range(5, -1, -1): m = (get_now() - relativedelta(months=i)).strftime("%m/%Y"); d.append(sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])); l.append(m[:2])
    plt.figure(figsize=(6, 4)); plt.plot(l, d, marker='o', color='#00ffcc'); plt.grid(alpha=0.3)
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close(); await query.message.reply_photo(buf)

async def rep_nospend(update, context):
    query = update.callback_query; await query.answer(); m = get_now().strftime("%m/%Y")
    dg = {int(t['date'][:2]) for t in db["transactions"] if t['type']=='gasto' and m in t['date']}
    txt = f"📅 **Mapa ({m})**\n` D S T Q Q S S`\n"
    for d in range(1, 32): 
        if d > get_now().day: break 
        txt += f"{'🔴' if d in dg else '🟢'} "; 
        if d%7==0: txt+="\n"
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

async def menu_cats(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Criar", callback_data="c_add"), InlineKeyboardButton("❌ Excluir", callback_data="c_del")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("Categorias:", reply_markup=InlineKeyboardMarkup(kb))
async def c_add(update, context): query = update.callback_query; await query.answer(); kb = [[InlineKeyboardButton("Gasto", callback_data="nc_gasto"), InlineKeyboardButton("Ganho", callback_data="nc_ganho")]]; await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb)); return CAT_ADD_TYPE
async def c_type(update, context): context.user_data["nt"] = update.callback_query.data.replace("nc_", ""); await update.callback_query.edit_message_text("Nome:"); return CAT_ADD_NAME
async def c_save(update, context):
    t = context.user_data["nt"]; n = update.message.text
    if n not in db["categories"][t]: db["categories"][t].append(n); save_db(db)
    await update.message.reply_text("Criada!"); return await start(update, context)
async def c_del(update, context):
    kb = []; query = update.callback_query
    for t in ["gasto","ganho"]: kb.append([InlineKeyboardButton(f"🗑️ {c}", callback_data=f"dc_{t}_{c}")])
    kb.append([InlineKeyboardButton("🔙", callback_data="back")]); await update.callback_query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))
async def c_kill(update, context):
    _, t, n = update.callback_query.data.split("_"); 
    if n in db["categories"][t]: db["categories"][t].remove(n); save_db(db)
    await update.callback_query.edit_message_text("Apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

async def menu_shop(update, context):
    l = db["shopping_list"]; txt = "**🛒 Mercado:**\n" + "\n".join(l)
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt + "\nFale para adicionar!", reply_markup=InlineKeyboardMarkup(kb))
async def sl_c(update, context): db["shopping_list"] = []; save_db(db); await start(update, context)

async def menu_persona(update, context):
    kb = [[InlineKeyboardButton("Julius", callback_data="sp_julius"), InlineKeyboardButton("Zoeiro", callback_data="sp_zoeiro")], [InlineKeyboardButton("Padrão", callback_data="sp_padrao")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text("Persona:", reply_markup=InlineKeyboardMarkup(kb))
async def set_persona(update, context): db["config"]["persona"] = update.callback_query.data.replace("sp_", ""); save_db(db); await menu_conf(update, context)
async def backup(update, context): 
    with open(DB_FILE, "rb") as f: await update.callback_query.message.reply_document(f)

async def menu_subs(update, context):
    query = update.callback_query; await query.answer(); subs = db.get("subscriptions", [])
    total = sum(float(s['val']) for s in subs); txt = f"🔔 **ASSINATURAS**\nTotal: **R$ {total:.2f}**\n\n"
    if not subs: txt += "_Vazio._"
    else: 
        for s in subs: txt += f"• {s['name']}: R$ {s['val']} (Dia {s['day']})\n"
    kb = [[InlineKeyboardButton("➕ Add", callback_data="sub_add"), InlineKeyboardButton("🗑️ Del", callback_data="sub_del")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def sub_add_help(update, context): await update.callback_query.answer(); await update.callback_query.message.reply_text("Use:\n`/sub Netflix 55.90 15`")
async def sub_cmd(update, context):
    try:
        n, v, d = context.args[0], float(context.args[1].replace(',', '.')), int(context.args[2])
        if "subscriptions" not in db: db["subscriptions"] = []
        db["subscriptions"].append({"name": n, "val": v, "day": d}); save_db(db)
        await update.message.reply_text(f"✅ Assinatura {n} salva!")
    except: await update.message.reply_text("❌ Erro. Use: `/sub Nome Valor Dia`")
async def sub_del_menu(update, context):
    query = update.callback_query; await query.answer(); subs = db.get("subscriptions", [])
    kb = [[InlineKeyboardButton(f"🗑️ {s['name']}", callback_data=f"ds_{i}")] for i, s in enumerate(subs)]
    kb.append([InlineKeyboardButton("🔙", callback_data="menu_subs")]); await query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))
async def sub_delete(update, context):
    query = update.callback_query; idx = int(query.data.replace("ds_", "")); subs = db.get("subscriptions", [])
    if 0 <= idx < len(subs): subs.pop(idx); save_db(db); await query.answer("Removido!"); await menu_subs(update, context)

async def roleta(update, context):
    res = "😈 **COMPRA!**" if random.random() > 0.5 else "😇 **NÃO COMPRA!**"
    kb = [[InlineKeyboardButton("🔄 Girar de novo", callback_data="roleta")], [InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    try: await update.callback_query.edit_message_text(f"{res}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    except: await update.callback_query.edit_message_text(f"{res} .", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_dreams(update, context): await update.callback_query.edit_message_text("🛌 Use: `/sonho PS5 4000`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")
async def dream_cmd(update, context):
    try: v = float(context.args[-1]); s,_,_ = calc_stats(); m = v/(s if s>0 else 100); await update.message.reply_text(f"🛌 Leva {m:.1f} meses.")
    except: pass

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    start_keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, 'interval', minutes=1, args=[app])
    scheduler.start()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resgatar", redeem_key))
    app.add_handler(CommandHandler("sonho", dream_cmd)); app.add_handler(CommandHandler("sub", sub_cmd))
    
    reg_h = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(reg_start, pattern="^start_reg"),
            CallbackQueryHandler(reg_type, pattern="^reg_gasto"),
            CallbackQueryHandler(reg_type, pattern="^reg_ganho")
        ],
        states={
            REG_TYPE:[CallbackQueryHandler(reg_type)], 
            REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], 
            REG_CAT:[CallbackQueryHandler(reg_cat)], 
            REG_DESC:[MessageHandler(filters.TEXT, reg_fin), CallbackQueryHandler(reg_fin, pattern="^skip_d")]
        }, 
        fallbacks=[CallbackQueryHandler(back, pattern="^back")]
    )
    
    cat_h = ConversationHandler(entry_points=[CallbackQueryHandler(c_add, pattern="^c_add")], states={CAT_ADD_TYPE:[CallbackQueryHandler(c_type)], CAT_ADD_NAME:[MessageHandler(filters.TEXT, c_save)]}, fallbacks=[CallbackQueryHandler(back, pattern="^back")])
    
    debt_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_person"), CallbackQueryHandler(debt_action, pattern="^debt_(add|sub)")],
        states={
            DEBT_NAME: [MessageHandler(filters.TEXT, save_person_name)],
            DEBT_VAL: [MessageHandler(filters.TEXT, debt_save_val)]
        },
        fallbacks=[CallbackQueryHandler(back, pattern="^back")]
    )
    
    app.add_handler(reg_h); app.add_handler(cat_h); app.add_handler(debt_h)

    cbs = [("admin_panel", admin_panel), ("gen_", gen_key), ("input_key", ask_key), 
           ("menu_reports", menu_reports), ("rep_nospend", rep_nospend), ("rep_evo", rep_evo), ("rep_pdf", rep_pdf), ("rep_list", rep_list), ("rep_csv", rep_csv), ("rep_pie", rep_pie),
           ("menu_debts", menu_debts), ("edit_debt_", edit_debt_menu), ("debt_", debt_action),
           ("menu_cats", menu_cats), ("c_del", c_del), ("dc_", c_kill),
           ("menu_shop", menu_shop), ("sl_c", sl_c),
           ("menu_conf", menu_conf), ("tg_panic", tg_panic), ("tg_travel", tg_travel), 
           ("menu_persona", menu_persona), ("sp_", set_persona), 
           ("backup", backup), ("undo_quick", undo_quick), ("back", back), 
           ("roleta", roleta), ("menu_subs", menu_subs), ("menu_dreams", menu_dreams),
           ("sub_add", sub_add_help), ("sub_del", sub_del_menu), ("ds_", sub_delete),
           ("menu_agenda", menu_agenda), ("del_agenda_", agenda_del)]
    for p, f in cbs: app.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO | filters.Document.ALL, restricted(smart_entry)))
    print("💎 V59 FINAL FIX RODANDO!")
    app.run_polling(drop_pending_updates=True)
