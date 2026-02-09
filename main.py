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

# ================= AUTO-CORREÇÃO DE INSTALAÇÃO =================
def install_package(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except:
        pass

try:
    from flask import Flask
except ImportError:
    install_package("flask")
    from flask import Flask

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
    install_package("python-telegram-bot")
    install_package("google-generativeai>=0.7.0")
    install_package("matplotlib")
    install_package("reportlab")
    install_package("python-dateutil")
    
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
    if "," in users_env:
        ADMIN_ID = int(users_env.split(",")[0])
    else:
        ADMIN_ID = int(users_env)
except:
    ADMIN_ID = 0

DB_FILE = "finance_v41_full.json"

# ================= KEEP ALIVE =================
app = Flask('')

@app.route('/')
def home():
    return "Bot Financeiro V41 (Completo) Online!"

def run_http():
    port_env = os.environ.get("PORT", "10000")
    try:
        port = int(port_env)
    except:
        port = 10000
    try:
        app.run(host='0.0.0.0', port=port)
    except:
        pass

def start_keep_alive():
    t = threading.Thread(target=run_http)
    t.daemon = True
    t.start()

# ================= VISUAL =================
plt.style.use('dark_background')
COLORS = ['#ff9999','#66b3ff','#99ff99','#ffcc99', '#c2c2f0','#ffb3e6', '#c4e17f']

def get_now():
    return datetime.utcnow() - timedelta(hours=3)

# ================= IA SETUP =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        chosen = next((m for m in models if 'flash' in m), next((m for m in models if 'gemini-pro' in m), None))
        if not chosen:
            chosen = 'gemini-pro'
        model_ai = genai.GenerativeModel(chosen)
    except: 
        try:
            model_ai = genai.GenerativeModel('gemini-pro')
        except:
            model_ai = None

# ================= BANCO DE DADOS =================
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
        "shopping_list": [], "debts": [],
        "user_level": {"xp": 0, "title": "Iniciante 🌱"},
        "config": {"persona": "padrao", "panic_mode": False, "travel_mode": False}
    }
    if not os.path.exists(DB_FILE):
        return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            for k in default: 
                if k not in data:
                    data[k] = default[k]
            return data
    except:
        return default

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

db = load_db()

# ================= SISTEMA VIP =================
def is_vip(user_id):
    if user_id == ADMIN_ID:
        return True, "👑 ADMIN (DONO)"
    
    uid_str = str(user_id)
    if uid_str in db["vip_users"]:
        data_str = db["vip_users"][uid_str]
        try:
            validade = datetime.strptime(data_str, "%Y-%m-%d")
            if validade > get_now():
                dias = (validade - get_now()).days
                return True, f"✅ VIP Ativo ({dias} dias)"
        except:
            pass
            
    return False, "❌ Expirado/Sem Acesso"

def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        status, msg = is_vip(user_id)
        if not status:
            kb = [[InlineKeyboardButton("🔑 Tenho uma Chave", callback_data="input_key")]]
            await update.message.reply_text(f"🚫 **ACESSO BLOQUEADO**\n\nCompre sua chave VIP com o dono.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ================= ADMIN =================
async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    query = update.callback_query
    if query:
        await query.answer()
    
    uc = len(db["vip_users"])
    kc = len([k for k, v in db["vip_keys"].items() if not v['used']])
    txt = f"👑 **PAINEL DO DONO**\n👥 Clientes: {uc}\n🔑 Chaves Livres: {kc}\n\n**Criar Chave:**"
    kb = [
        [InlineKeyboardButton("📅 30 Dias", callback_data="gen_30"), InlineKeyboardButton("📅 90 Dias", callback_data="gen_90")],
        [InlineKeyboardButton("📅 7 Dias", callback_data="gen_7"), InlineKeyboardButton("♾️ 1 Ano", callback_data="gen_365")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="back")]
    ]
    if query:
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def gen_key(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()
    days = int(query.data.replace("gen_", ""))
    key = f"VIP-{uuid.uuid4().hex[:6].upper()}"
    db["vip_keys"][key] = {"days": days, "used": False}
    save_db(db)
    await query.message.reply_text(f"✅ **Chave Criada!**\n`{key}`\n📅 {days} dias", parse_mode="Markdown")
    await admin_panel(update, context)

# ================= CLIENTE =================
async def ask_key(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✍️ Use: `/resgatar CODIGO`", parse_mode="Markdown")

async def redeem_key(update, context):
    uid = str(update.effective_user.id)
    try:
        key = context.args[0].strip()
    except:
        await update.message.reply_text("❌ Use: `/resgatar CHAVE`")
        return
    
    kd = db["vip_keys"].get(key)
    if not kd or kd["used"]:
        await update.message.reply_text("❌ Chave inválida.")
        return
    
    days = kd["days"]
    curr = db["vip_users"].get(uid)
    
    base_date = get_now()
    if curr:
        try:
            curr_date = datetime.strptime(curr, "%Y-%m-%d")
            if curr_date > get_now():
                base_date = curr_date
        except:
            pass
            
    new_d = base_date + timedelta(days=days)
    db["vip_users"][uid] = new_d.strftime("%Y-%m-%d")
    db["vip_keys"][key]["used"] = True
    save_db(db)
    await update.message.reply_text(f"🎉 **VIP ATIVADO!**\nVence: {new_d.strftime('%d/%m/%Y')}\nDigite /start", parse_mode="Markdown")

# ================= AUXILIARES =================
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME) = range(6)

def update_level():
    xp = len(db["transactions"])
    titles = [(0,"Iniciante"),(20,"Aprendiz"),(50,"Analista"),(100,"Gerente"),(500,"Magnata")]
    curr = db["user_level"]["title"]
    new_t = curr
    for limit, title in titles:
        if xp >= limit:
            new_t = title
    
    db["user_level"] = {"xp":xp, "title":new_t}
    return new_t != curr, new_t

def calc_stats():
    n = get_now()
    m = n.strftime("%m/%Y")
    gan = sum(t['value'] for t in db["transactions"] if t['type']=='ganho' and m in t['date'])
    gas = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])
    return (gan-gas), gan, gas

def check_budget(cat, val):
    lim = db["budgets"].get(cat, 0)
    m = get_now().strftime("%m/%Y")
    if lim == 0:
        return None
    curr = sum(t['value'] for t in db["transactions"] if t['category']==cat and t['type']=='gasto' and m in t['date'])
    if (curr+val) > lim:
        return f"🚨 Teto de {cat}!"
    return None

# ================= IA =================
@restricted
async def smart_entry(update, context):
    if not model_ai:
        await update.message.reply_text("⚠️ IA Offline.")
        return
    msg = update.message
    
    # Comandos Rápidos
    if msg.text == "💸 Gasto": return await reg_start(update, context)
    if msg.text == "💰 Ganho": 
        update.callback_query = type('obj', (object,), {'answer': lambda: None, 'edit_message_text': lambda x, reply_markup: msg.reply_text(x, reply_markup=reply_markup), 'data': 'reg_ganho'})
        return await reg_type(update, context)
    if msg.text == "📊 Relatórios": return await menu_reports(update, context)
    if msg.text == "👛 Saldo": return await start(update, context)

    travel = db["config"]["travel_mode"]
    panic = db["config"]["panic_mode"]
    role_map = {"julius":"Julius Rock", "primo":"Primo Rico", "mae":"Mãe", "zoeiro":"Zoeiro", "padrao":"Assistente"}
    role = role_map.get(db["config"]["persona"], "Assistente")

    if panic and msg.text:
        bad_words = ["lazer","cerveja","pizza","bar","ifood","uber"]
        if any(b in msg.text.lower() for b in bad_words):
            await msg.reply_text("🛑 PÂNICO ATIVO!")
            return

    wait = await msg.reply_text("🎤..." if (msg.voice or msg.audio) else "🧠...")
    try:
        content = []
        prompt = f"""Atue como {role}. Travel={travel}. 1. JSON: {{"type":"gasto/ganho","value":float,"category":"str","description":"str","installments":1,"comment":"str"}}. 2. Texto."""
        content.append(prompt)
        file_path = None
        
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id)
            d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": d})
        elif msg.voice or msg.audio:
            fid = (msg.voice or msg.audio).file_id
            f = await context.bot.get_file(fid)
            ext = ".ogg" if msg.voice else ".mp3"
            file_path = f"aud_{uuid.uuid4()}{ext}"
            await f.download_to_drive(file_path)
            try:
                up = genai.upload_file(file_path)
                while up.state.name == "PROCESSING":
                    time.sleep(1)
                content.append(up)
            except:
                if os.path.exists(file_path): os.remove(file_path)
                await wait.edit_text("Erro upload.")
                return
        else:
            content.append(f"Input: {msg.text}")
            
        resp = model_ai.generate_content(content)
        txt = resp.text.strip().replace("```json", "").replace("```", "")
        
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        
        data = None
        if "{" in txt:
            try:
                data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
            except: 
                try:
                    data = ast.literal_eval(txt[txt.find("{"):txt.rfind("}")+1])
                except:
                    pass
        
        if data:
            if data['type']=='gasto' and check_budget(data['category'], float(data['value'])) and panic:
                await wait.edit_text("🛑 Teto!")
                return
            
            inst = data.get("installments", 1)
            val = float(data['value'])
            
            for i in range(inst):
                dt = get_now() + relativedelta(months=i)
                desc = data['description']
                if inst > 1:
                    desc += f" ({i+1}/{inst})"
                
                t = {"id":str(uuid.uuid4())[:8], "type":data['type'], "value":val/inst if inst>1 else val, "category":data['category'], "description":desc, "date":dt.strftime("%d/%m/%Y %H:%M")}
                db["transactions"].append(t)
            
            lv, ti = update_level()
            save_db(db)
            context.user_data["last_id"] = t["id"]
            
            msg_ok = f"✅ **R$ {val:.2f}** | {data['category']}\n📝 {data['description']}"
            if inst>1:
                msg_ok += f"\n📅 {inst}x"
            if data.get('comment'):
                msg_ok += f"\n\n🗣️ {data['comment']}"
            
            kb = [[InlineKeyboardButton("↩️ Desfazer", callback_data="undo_quick")]]
            await wait.edit_text(msg_ok, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await wait.edit_text(txt)
            
    except Exception as e:
        await wait.edit_text(f"⚠️ Erro: {e}")

async def undo_quick(update, context):
    query = update.callback_query
    await query.answer()
    lid = context.user_data.get("last_id")
    if lid:
        db["transactions"] = [t for t in db["transactions"] if t['id'] != lid]
        save_db(db)
        await query.edit_message_text("🗑️ Desfeito!")
    else:
        await query.edit_message_text("Nada para desfazer.")

# ================= MENU =================
@restricted
async def start(update, context):
    context.user_data.clear()
    saldo, ganho, gasto = calc_stats()
    uid = update.effective_user.id
    vip_ok, vip_msg = is_vip(uid)
    
    kb_inline = [
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
        [InlineKeyboardButton("🤝 Dívidas", callback_data="menu_debts"), InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🎲 Roleta", callback_data="roleta"), InlineKeyboardButton("🔮 Sonhos", callback_data="menu_dreams")],
        [InlineKeyboardButton("⚙️ Configs", callback_data="menu_conf"), InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]
    
    if uid == ADMIN_ID:
        kb_inline.insert(0, [InlineKeyboardButton("👑 PAINEL DO DONO", callback_data="admin_panel")])
        
    kb_reply = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    
    msg = f"💎 **FINANCEIRO V41 (FULL)**\n{vip_msg}\n💰 Saldo: **R$ {saldo:.2f}**\n📉 Gastos: R$ {gasto:.2f}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_inline), parse_mode="Markdown")
        try:
            m = await context.bot.send_message(chat_id=update.effective_chat.id, text="...", reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True))
            await m.delete()
        except:
            pass
    else:
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True), parse_mode="Markdown")
        await update.message.reply_text("⚙️ **Menu:**", reply_markup=InlineKeyboardMarkup(kb_inline))
    return ConversationHandler.END

async def back(update, context): 
    if update.callback_query:
        await update.callback_query.answer()
    await start(update, context)

# ================= SUB-MENUS & EXTRAS =================
async def menu_conf(update, context):
    p = "🔴" if db["config"]["panic_mode"] else "🟢"
    t = "✈️" if db["config"]["travel_mode"] else "🏠"
    kb = [
        [InlineKeyboardButton(f"Pânico: {p}", callback_data="tg_panic"), InlineKeyboardButton(f"Viagem: {t}", callback_data="tg_travel")],
        [InlineKeyboardButton("🎭 Persona", callback_data="menu_persona"), InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")],
        [InlineKeyboardButton("🔙", callback_data="back")]
    ]
    await update.callback_query.edit_message_text("⚙️ **Configurações:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_reports(update, context):
    if not update.callback_query:
        msg = await update.message.reply_text("🔄")
        update.callback_query = type('obj', (object,), {'answer': lambda: None, 'edit_message_text': lambda x, reply_markup: msg.edit_text(x, reply_markup=reply_markup), 'message': msg})
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("📅 Mapa", callback_data="rep_nospend"), InlineKeyboardButton("📉 Evolução", callback_data="rep_evo")], [InlineKeyboardButton("📄 PDF", callback_data="rep_pdf"), InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("📊 **Relatórios:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def rep_nospend(update, context):
    query = update.callback_query
    await query.answer()
    m = get_now().strftime("%m/%Y")
    dg = {int(t['date'][:2]) for t in db["transactions"] if t['type']=='gasto' and m in t['date']}
    txt = f"📅 **Mapa ({m})**\n` D S T Q Q S S`\n"
    for d in range(1, 32): 
        if d > get_now().day:
            break 
        txt += f"{'🔴' if d in dg else '🟢'} "
        if d%7==0:
            txt+="\n"
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")

async def rep_evo(update, context):
    query = update.callback_query
    await query.answer()
    d, l = [], []
    for i in range(5, -1, -1):
        m = (get_now() - relativedelta(months=i)).strftime("%m/%Y")
        d.append(sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date']))
        l.append(m[:2])
    plt.figure(figsize=(6, 4))
    plt.plot(l, d, marker='o', color='#00ffcc')
    plt.grid(alpha=0.3)
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    await query.message.reply_photo(buf)

async def rep_pdf(update, context):
    query = update.callback_query
    await query.answer()
    c = canvas.Canvas("rel.pdf", pagesize=letter)
    c.drawString(100,750,f"Extrato VIP")
    c.save()
    with open("rel.pdf", "rb") as f:
        await query.message.reply_document(f)

# REGISTRO MANUAL
async def reg_start(update, context): 
    if not update.callback_query:
        msg = await update.message.reply_text("🔄")
        update.callback_query = type('obj', (object,), {'answer': lambda: None, 'edit_message_text': lambda x, reply_markup: msg.edit_text(x, reply_markup=reply_markup)})
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("💸 Gasto", callback_data="reg_gasto"), InlineKeyboardButton("💰 Ganho", callback_data="reg_ganho")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "start":
        return await start(update, context)
    context.user_data["t"] = query.data.replace("reg_", "")
    await query.edit_message_text("Valor:")
    return REG_VALUE

async def reg_val(update, context): 
    try:
        context.user_data["v"] = float(update.message.text.replace(',', '.'))
    except:
        return REG_VALUE
    cats = db["categories"][context.user_data["t"]]
    kb = []
    for i in range(0, len(cats), 2):
        kb.append([InlineKeyboardButton(c, callback_data=f"sc_{c}") for c in cats[i:i+2]])
    await update.message.reply_text("Categoria:", reply_markup=InlineKeyboardMarkup(kb))
    return REG_CAT

async def reg_cat(update, context):
    context.user_data["c"] = update.callback_query.data.replace("sc_", "")
    kb = [[InlineKeyboardButton("⏩ Pular", callback_data="skip_d")]]
    await update.callback_query.edit_message_text("Descrição:", reply_markup=InlineKeyboardMarkup(kb))
    return REG_DESC

async def reg_fin(update, context):
    desc = update.message.text if update.message else "Manual"
    if update.callback_query and update.callback_query.data == "skip_d":
        desc = context.user_data["c"]
    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":context.user_data["t"], "value":context.user_data["v"], "category":context.user_data["c"], "description":desc, "date":get_now().strftime("%d/%m/%Y %H:%M")})
    save_db(db)
    await (update.message or update.callback_query.message).reply_text("✅ Salvo!")
    return await start(update, context)

# EXTRAS
async def menu_debts(update, context):
    d = db["debts"]
    txt = "**🤝 Dívidas:**\n" + ("".join([f"{x['who']}: {x['val']}\n" for x in d]) if d else "Vazio.")
    kb = [[InlineKeyboardButton("➕ Add", callback_data="add_d"), InlineKeyboardButton("🗑️ Limpar", callback_data="cl_d")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_debt_help(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Use: `/devo Nome 10`")

async def debt_cmd(update, context): 
    try:
        db["debts"].append({"who":context.args[0], "val":context.args[1], "type":"owe"})
        save_db(db)
        await update.message.reply_text("Ok!")
    except:
        pass

async def cl_d(update, context):
    db["debts"] = []
    save_db(db)
    await menu_debts(update, context)

async def menu_cats(update, context):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("➕ Criar", callback_data="c_add"), InlineKeyboardButton("❌ Excluir", callback_data="c_del")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("Categorias:", reply_markup=InlineKeyboardMarkup(kb))

async def c_add(update, context):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="nc_gasto"), InlineKeyboardButton("Ganho", callback_data="nc_ganho")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb))
    return CAT_ADD_TYPE

async def c_type(update, context):
    context.user_data["nt"] = update.callback_query.data.replace("nc_", "")
    await update.callback_query.edit_message_text("Nome:")
    return CAT_ADD_NAME

async def c_save(update, context):
    t = context.user_data["nt"]
    n = update.message.text
    if n not in db["categories"][t]:
        db["categories"][t].append(n)
        save_db(db)
    await update.message.reply_text("Criada!")
    return await start(update, context)

async def c_del(update, context):
    kb = []
    query = update.callback_query
    for t in ["gasto","ganho"]: 
        for c in db["categories"][t]:
            kb.append([InlineKeyboardButton(f"🗑️ {c}", callback_data=f"dc_{t}_{c}")])
    kb.append([InlineKeyboardButton("🔙", callback_data="back")])
    await update.callback_query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))

async def c_kill(update, context):
    _, t, n = update.callback_query.data.split("_")
    if n in db["categories"][t]:
        db["categories"][t].remove(n)
        save_db(db)
    await update.callback_query.edit_message_text("Apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

async def menu_shop(update, context):
    l = db["shopping_list"]
    txt = "**🛒 Mercado:**\n" + "\n".join(l)
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt + "\nFale para adicionar!", reply_markup=InlineKeyboardMarkup(kb))

async def sl_c(update, context):
    db["shopping_list"] = []
    save_db(db)
    await start(update, context)

async def tg_panic(update, context):
    db["config"]["panic_mode"] = not db["config"]["panic_mode"]
    save_db(db)
    await start(update, context)

async def tg_travel(update, context):
    db["config"]["travel_mode"] = not db["config"]["travel_mode"]
    save_db(db)
    await start(update, context)

async def menu_persona(update, context):
    kb = [[InlineKeyboardButton("Julius", callback_data="sp_julius"), InlineKeyboardButton("Zoeiro", callback_data="sp_zoeiro")], [InlineKeyboardButton("Padrão", callback_data="sp_padrao")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text("Persona:", reply_markup=InlineKeyboardMarkup(kb))

async def set_persona(update, context):
    db["config"]["persona"] = update.callback_query.data.replace("sp_", "")
    save_db(db)
    await start(update, context)

async def backup(update, context): 
    with open(DB_FILE, "rb") as f:
        await update.callback_query.message.reply_document(f)

# --- FUNÇÕES QUE FALTAVAM ---
async def roleta(update, context):
    await update.callback_query.edit_message_text("😈 **COMPRA!**" if random.random()>0.5 else "😇 **NÃO COMPRA!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")

async def menu_subs(update, context):
    await update.callback_query.edit_message_text("🔔 Assinaturas (Em breve)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

async def menu_dreams(update, context):
    await update.callback_query.edit_message_text("🛌 Use: `/sonho PS5 4000`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")

async def dream_cmd(update, context):
    try:
        v = float(context.args[-1])
        s,_,_ = calc_stats()
        m = v/(s if s>0 else 100)
        await update.message.reply_text(f"🛌 Leva {m:.1f} meses.")
    except:
        pass

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    start_keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resgatar", redeem_key))
    app.add_handler(CommandHandler("devo", debt_cmd))
    app.add_handler(CommandHandler("sonho", dream_cmd))
    
    reg_h = ConversationHandler(entry_points=[CallbackQueryHandler(reg_start, pattern="^start_reg")], states={REG_TYPE:[CallbackQueryHandler(reg_type)], REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], REG_CAT:[CallbackQueryHandler(reg_cat)], REG_DESC:[MessageHandler(filters.TEXT, reg_fin), CallbackQueryHandler(reg_fin, pattern="^skip_d")]}, fallbacks=[CallbackQueryHandler(back, pattern="^back")])
    cat_h = ConversationHandler(entry_points=[CallbackQueryHandler(c_add, pattern="^c_add")], states={CAT_ADD_TYPE:[CallbackQueryHandler(c_type)], CAT_ADD_NAME:[MessageHandler(filters.TEXT, c_save)]}, fallbacks=[CallbackQueryHandler(back, pattern="^back")])
    app.add_handler(reg_h); app.add_handler(cat_h)

    cbs = [("admin_panel", admin_panel), ("gen_", gen_key), ("input_key", ask_key), 
           ("menu_reports", menu_reports), ("rep_nospend", rep_nospend), ("rep_evo", rep_evo), ("rep_pdf", rep_pdf),
           ("menu_debts", menu_debts), ("add_d", add_debt_help), ("cl_d", cl_d),
           ("menu_cats", menu_cats), ("c_del", c_del), ("dc_", c_kill),
           ("menu_shop", menu_shop), ("sl_c", sl_c),
           ("menu_conf", menu_conf), ("tg_panic", tg_panic), ("tg_travel", tg_travel), 
           ("menu_persona", menu_persona), ("sp_", set_persona), 
           ("backup", backup), ("undo_quick", undo_quick), ("back", back), 
           ("reg_gasto", reg_type), ("reg_ganho", reg_type),
           ("roleta", roleta), ("menu_subs", menu_subs), ("menu_dreams", menu_dreams)]
    for p, f in cbs: app.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO, restricted(smart_entry)))
    print("💎 V41 FULL RODANDO!")
    app.run_polling(drop_pending_updates=True)
