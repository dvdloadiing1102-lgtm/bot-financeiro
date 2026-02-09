import os
import json
import logging
import uuid
import io
import csv
import ast
import time
import math
import random
import threading
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
from flask import Flask

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip().isdigit()]
DB_FILE = "finance_v36_final.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= KEEP ALIVE (PARA O RENDER NÃO DERRUBAR) =================
# Isso cria um site falso para enganar o Render e evitar o erro "Port scan timeout"
app = Flask('')

@app.route('/')
def home():
    return "Bot Financeiro está rodando e saudável!"

def run_http():
    # Pega a porta que o Render exige ou usa 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def start_keep_alive():
    t = threading.Thread(target=run_http)
    t.start()

# ================= ESTILO VISUAL =================
plt.style.use('dark_background')
COLORS = ['#ff9999','#66b3ff','#99ff99','#ffcc99', '#c2c2f0','#ffb3e6', '#c4e17f']

def get_now(): return datetime.utcnow() - timedelta(hours=3)

# ================= IA SETUP =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        chosen = next((m for m in models if 'flash' in m), next((m for m in models if 'gemini-pro' in m), None))
        if not chosen: chosen = 'gemini-pro'
        model_ai = genai.GenerativeModel(chosen)
        logger.info(f"IA Conectada: {chosen}")
    except: 
        try: model_ai = genai.GenerativeModel('gemini-pro')
        except: model_ai = None

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas", "Viagem"]
        }, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Crédito"],
        "budgets": {"Alimentação": 1000, "Lazer": 500},
        "subscriptions": [], "shopping_list": [], "debts": [],
        "user_level": {"xp": 0, "title": "Iniciante 🌱"},
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

# ================= ESTADOS =================
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME) = range(6)

# ================= HELPERS =================
def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USERS and user_id not in ALLOWED_USERS: return
        return await func(update, context, *args, **kwargs)
    return wrapped

def update_level():
    xp = len(db["transactions"])
    titles = [(0, "Iniciante 🌱"), (20, "Aprendiz 📝"), (50, "Analista 📊"), 
              (100, "Gerente 👔"), (200, "Diretor 🎩"), (500, "Magnata 🚀"), (1000, "Lobo de Wall St 🐺")]
    curr = db["user_level"]["title"]
    new_t = next((t for x, t in reversed(titles) if xp >= x), curr)
    db["user_level"] = {"xp": xp, "title": new_t}
    return new_t != curr, new_t

def calc_stats():
    now = get_now(); mes = now.strftime("%m/%Y")
    ganhos = sum(t['value'] for t in db["transactions"] if t['type']=='ganho' and mes in t['date'])
    gastos = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and mes in t['date'])
    return (ganhos - gastos), ganhos, gastos

def check_budget(cat, val):
    lim = db["budgets"].get(cat, 0)
    if lim == 0: return None
    mes = get_now().strftime("%m/%Y")
    atual = sum(t['value'] for t in db["transactions"] if t['category']==cat and t['type']=='gasto' and mes in t['date'])
    if (atual + val) > lim: return f"🚨 **ALERTA:** Teto de {cat} estourado!"
    return None

# ================= IA =================
@restricted
async def smart_entry(update, context):
    if not model_ai: 
        await update.message.reply_text("⚠️ IA Indisponível (Cheque requirements.txt).")
        return

    msg = update.message
    
    # Comandos de Texto (Menu Persistente)
    if msg.text == "💸 Registrar Gasto": return await reg_start(update, context)
    if msg.text == "💰 Registrar Ganho": 
        update.callback_query = type('obj', (object,), {'answer': lambda: None, 'edit_message_text': lambda x, reply_markup: msg.reply_text(x, reply_markup=reply_markup), 'data': 'reg_ganho'})
        return await reg_type(update, context)
    if msg.text == "📊 Relatórios": return await menu_reports(update, context)
    if msg.text == "👛 Saldo": return await start(update, context)

    travel = db["config"]["travel_mode"]
    panic = db["config"]["panic_mode"]
    persona_key = db["config"]["persona"]

    personas_prompt = {
        "julius": "Você é o Julius Rock. Pão-duro, rabugento, calcula preço em horas de trabalho.",
        "primo": "Você é o Primo Rico. Fale de 'mindset', 'aportes' e cortar gastos.",
        "mae": "Você é Mãe Brasileira. Pergunte se 'você acha que dinheiro dá em árvore'.",
        "zoeiro": "Você é comediante sarcástico. Faça piada da pobreza do usuário.",
        "padrao": "Você é um assistente financeiro eficiente."
    }
    system_role = personas_prompt.get(persona_key, personas_prompt["padrao"])

    if panic and msg.text:
        bad = ["lazer", "cerveja", "bar", "pizza", "mc", "burger", "ifood", "uber"]
        if any(b in msg.text.lower() for b in bad):
            await msg.reply_text("🛑 **PÂNICO ATIVO:** Compra bloqueada! Economize."); return

    wait = await msg.reply_text("🎤 Ouvindo..." if (msg.voice or msg.audio) else "🧠 Processando...")
    
    try:
        content = []
        file_path = None
        
        prompt = f"""
        {system_role}
        TravelMode={travel}.
        Analise o input.
        1. Se for financeiro, retorne JSON:
           {{"type": "gasto/ganho", "value": float, "category": "string", "wallet": "string", "description": "string", "installments": 1, "comment": "Seu comentário curto"}}
        2. Se parcelado ("10x"), installments=10.
        3. Se não for financeiro, responda apenas texto.
        """
        content.append(prompt)
        
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
                up_file = genai.upload_file(file_path)
                while up_file.state.name == "PROCESSING": time.sleep(1)
                content.append(up_file)
            except:
                if os.path.exists(file_path): os.remove(file_path)
                await wait.edit_text("❌ Erro upload áudio. Tente texto.")
                return
        else:
            content.append(f"Input: {msg.text}")
            
        resp = model_ai.generate_content(content)
        txt = resp.text.strip().replace("```json", "").replace("```", "")
        
        if file_path and os.path.exists(file_path): os.remove(file_path)
        
        data = None
        if "{" in txt:
            try: data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
            except: 
                try: data = ast.literal_eval(txt[txt.find("{"):txt.rfind("}")+1])
                except: pass
        
        if data:
            if data['type']=='gasto' and check_budget(data['category'], float(data['value'])) and panic:
                await wait.edit_text("🛑 Bloqueado pelo Teto de Gastos!"); return
            
            inst = data.get("installments", 1)
            val = float(data['value'])
            
            for i in range(inst):
                dt = get_now() + relativedelta(months=i)
                desc = data['description']
                if inst > 1: desc += f" ({i+1}/{inst})"
                
                t = {
                    "id": str(uuid.uuid4())[:8],
                    "type": data['type'], "value": val/inst if inst>1 else val,
                    "category": data['category'], "wallet": data.get('wallet', 'Manual'),
                    "description": desc, "date": dt.strftime("%d/%m/%Y %H:%M")
                }
                db["transactions"].append(t)
            
            levelup, title = update_level()
            save_db(db)
            context.user_data["last_id"] = t["id"]
            
            comment = data.get('comment', '')
            
            msg_ok = f"✅ **R$ {val:.2f}** | {data['category']}\n📝 {data['description']}"
            if inst>1: msg_ok += f"\n📅 {inst}x parcelas"
            if comment: msg_ok += f"\n\n🗣️ {comment}"
            if levelup: msg_ok += f"\n🎉 **LEVEL UP:** {title}"
            
            kb = [[InlineKeyboardButton("↩️ Desfazer", callback_data="undo_quick")]]
            await wait.edit_text(msg_ok, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await wait.edit_text(txt)

    except Exception as e:
        await wait.edit_text(f"⚠️ Erro IA: {e}")

async def undo_quick(update, context):
    query = update.callback_query; await query.answer()
    lid = context.user_data.get("last_id")
    if lid:
        db["transactions"] = [t for t in db["transactions"] if t['id'] != lid]
        save_db(db)
        await query.edit_message_text("🗑️ Registro desfeito!")
    else:
        await query.edit_message_text("Nada para desfazer.")

# ================= MENU =================
@restricted
async def start(update, context):
    context.user_data.clear()
    saldo, ganho, gasto = calc_stats()
    lvl = db["user_level"]["title"]
    
    st_panic = "🔴" if db["config"]["panic_mode"] else "🟢"
    st_travel = "✈️ ON" if db["config"]["travel_mode"] else "🏠"
    
    kb_inline = [
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
        [InlineKeyboardButton("🤝 Dívidas", callback_data="menu_debts"), InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")],
        [InlineKeyboardButton("🎲 Roleta", callback_data="roleta"), InlineKeyboardButton("🔮 Sonhos", callback_data="menu_dreams")],
        [InlineKeyboardButton(f"Pânico: {st_panic}", callback_data="tg_panic"), InlineKeyboardButton(f"Viagem: {st_travel}", callback_data="tg_travel")],
        [InlineKeyboardButton("🎭 Persona", callback_data="menu_persona"), InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]

    kb_reply = [["💸 Registrar Gasto", "💰 Registrar Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    
    msg = (f"💎 **FINANCEIRO V36 (FINAL)**\n"
           f"👤 {lvl}\n"
           f"──────────────\n"
           f"💰 Saldo: **R$ {saldo:.2f}**\n"
           f"📈 Entrou: R$ {ganho:.2f}\n"
           f"📉 Saiu:   R$ {gasto:.2f}\n"
           f"──────────────\n"
           f"🎙️ *Pode falar, mandar foto ou texto!*")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_inline), parse_mode="Markdown")
        m = await context.bot.send_message(chat_id=update.effective_chat.id, text="...", reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True))
        await m.delete()
    else:
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True), parse_mode="Markdown")
        await update.message.reply_text("⚙️ **Painel:**", reply_markup=InlineKeyboardMarkup(kb_inline))
    return ConversationHandler.END

async def back(update, context): 
    if update.callback_query: await update.callback_query.answer()
    await start(update, context)

# ================= MÓDULOS EXTRAS =================
async def tg_panic(update, context): db["config"]["panic_mode"] = not db["config"]["panic_mode"]; save_db(db); await start(update, context)
async def tg_travel(update, context): db["config"]["travel_mode"] = not db["config"]["travel_mode"]; save_db(db); await start(update, context)

async def menu_debts(update, context):
    d = db["debts"]; txt = "**🤝 Dívidas:**\n" + ("".join([f"{x['who']}: {x['val']}\n" for x in d]) if d else "Vazio.")
    kb = [[InlineKeyboardButton("➕ Adicionar", callback_data="add_d"), InlineKeyboardButton("🗑️ Limpar", callback_data="cl_d")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def add_debt_help(update, context): await update.callback_query.answer(); await update.callback_query.message.reply_text("Use:\n`/devo Nome 10`\n`/receber Nome 50`")
async def debt_cmd(update, context):
    try: t = "owe" if "devo" in update.message.text else "rec"; db["debts"].append({"who":context.args[0], "val":context.args[1], "type":t}); save_db(db); await update.message.reply_text("Ok!")
    except: pass
async def cl_d(update, context): db["debts"] = []; save_db(db); await menu_debts(update, context)

async def menu_cats(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Criar", callback_data="c_add"), InlineKeyboardButton("❌ Excluir", callback_data="c_del")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("Categorias:", reply_markup=InlineKeyboardMarkup(kb))
async def c_add(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="nc_gasto"), InlineKeyboardButton("Ganho", callback_data="nc_ganho")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb)); return CAT_ADD_TYPE
async def c_type(update, context):
    context.user_data["nt"] = update.callback_query.data.replace("nc_", "")
    await update.callback_query.edit_message_text("Nome:"); return CAT_ADD_NAME
async def c_save(update, context):
    t = context.user_data["nt"]; n = update.message.text
    if n not in db["categories"][t]: db["categories"][t].append(n); save_db(db)
    await update.message.reply_text("Criada!"); return await start(update, context)
async def c_del(update, context):
    kb = []; q = update.callback_query
    for t in ["gasto","ganho"]:
        for c in db["categories"][t]: kb.append([InlineKeyboardButton(f"🗑️ {c}", callback_data=f"dc_{t}_{c}")])
    kb.append([InlineKeyboardButton("🔙", callback_data="back")])
    await update.callback_query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))
async def c_kill(update, context):
    _, t, n = update.callback_query.data.split("_")
    if n in db["categories"][t]: db["categories"][t].remove(n); save_db(db)
    await update.callback_query.edit_message_text("Apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

async def menu_shop(update, context):
    l = db["shopping_list"]; txt = "**🛒 Mercado:**\n" + "\n".join(l)
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt + "\nFale para adicionar!", reply_markup=InlineKeyboardMarkup(kb))
async def sl_c(update, context): db["shopping_list"] = []; save_db(db); await start(update, context)

async def roleta(update, context): await update.callback_query.edit_message_text("😈 **COMPRA!**" if random.random()>0.5 else "😇 **NÃO COMPRA!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")
async def menu_persona(update, context):
    kb = [[InlineKeyboardButton("Julius", callback_data="sp_julius"), InlineKeyboardButton("Zoeiro", callback_data="sp_zoeiro")], [InlineKeyboardButton("Padrão", callback_data="sp_padrao")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text("Persona:", reply_markup=InlineKeyboardMarkup(kb))
async def set_persona(update, context): db["config"]["persona"] = update.callback_query.data.replace("sp_", ""); save_db(db); await start(update, context)
async def menu_subs(update, context): await update.callback_query.edit_message_text("🔔 Assinaturas (Em breve)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))
async def menu_dreams(update, context): await update.callback_query.edit_message_text("🛌 Use: `/sonho PS5 4000`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")
async def dream_cmd(update, context):
    try: v = float(context.args[-1]); s,_,_,_ = calc_stats(); m = v/(s if s>0 else 100)
    except: pass; await update.message.reply_text(f"🛌 Leva {m:.1f} meses.")
async def backup(update, context):
    with open(DB_FILE, "rb") as f: await update.callback_query.message.reply_document(f)

# ================= RELATÓRIOS =================
async def menu_reports(update, context):
    if not update.callback_query: 
        msg = await update.message.reply_text("🔄")
        update.callback_query = type('obj', (object,), {'answer': lambda: None, 'edit_message_text': lambda x, reply_markup: msg.edit_text(x, reply_markup=reply_markup), 'message': msg})

    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📅 Mapa Calor", callback_data="rep_nospend"), InlineKeyboardButton("📉 Evolução", callback_data="rep_evo")],
          [InlineKeyboardButton("📄 PDF", callback_data="rep_pdf"), InlineKeyboardButton("📊 Excel", callback_data="rep_csv")],
          [InlineKeyboardButton("🍕 Categorias", callback_data="rep_pie"), InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("📊 **Relatórios:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def rep_pie(update, context):
    query = update.callback_query; await query.answer()
    cats = {}
    mes = get_now().strftime("%m/%Y")
    for t in db["transactions"]:
        if t['type']=='gasto' and mes in t['date']: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    if not cats: await query.edit_message_text("Sem dados.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]])); return
    
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.pie(cats.values(), autopct='%1.1f%%', startangle=90, colors=COLORS)
    ax.legend(cats.keys(), loc="best")
    ax.set_title(f"Gastos {mes}", color='white')
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)

async def rep_evo(update, context):
    query = update.callback_query; await query.answer(); d, l = [], []
    for i in range(5, -1, -1):
        m = (get_now() - relativedelta(months=i)).strftime("%m/%Y")
        d.append(sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])); l.append(m[:2])
    plt.figure(figsize=(6, 4)); plt.plot(l, d, marker='o', color='#00ffcc'); plt.grid(alpha=0.3); plt.title("Evolução")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)

async def rep_nospend(update, context):
    query = update.callback_query; await query.answer(); m = get_now().strftime("%m/%Y")
    dg = {int(t['date'][:2]) for t in db["transactions"] if t['type']=='gasto' and m in t['date']}
    txt = f"📅 **Mapa ({m})**\n\n` D  S  T  Q  Q  S  S`\n"
    for d in range(1, 32):
        if d > get_now().day: break
        txt += f"{'🔴' if d in dg else '🟢'}  "; 
        if d%7==0: txt+="\n"
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")

async def rep_csv(update, context):
    query = update.callback_query; await query.answer()
    with open("extrato.csv", "w", newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';'); w.writerow(["Data", "Tipo", "Valor", "Categoria", "Descricao"])
        for t in db["transactions"]: w.writerow([t['date'], t['type'], str(t['value']).replace('.',','), t['category'], t['description']])
    with open("extrato.csv", "rb") as f: await query.message.reply_document(f)
async def rep_pdf(update, context):
    query = update.callback_query; await query.answer()
    c = canvas.Canvas("rel.pdf", pagesize=letter); c.drawString(100,750,f"Extrato V36"); c.save()
    with open("rel.pdf", "rb") as f: await query.message.reply_document(f)

async def help_search(update, context): await update.callback_query.message.reply_text("🔎 `/buscar termo`")
async def search_cmd(update, context):
    t = " ".join(context.args).lower(); res = [x for x in db["transactions"] if t in x['description'].lower()]
    await update.message.reply_text(f"🔎 Achei {len(res)} itens. Total: R$ {sum(r['value'] for r in res):.2f}")

# ================= MANUAL & EXTRAS =================
async def reg_start(update, context):
    if not update.callback_query: 
        msg = await update.message.reply_text("🔄")
        update.callback_query = type('obj', (object,), {'answer': lambda: None, 'edit_message_text': lambda x, reply_markup: msg.edit_text(x, reply_markup=reply_markup)})
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("💸 Gasto", callback_data="reg_gasto"), InlineKeyboardButton("💰 Ganho", callback_data="reg_ganho")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb)); return REG_TYPE
async def reg_type(update, context):
    query = update.callback_query; await query.answer(); 
    if query.data == "start": return await start(update, context)
    context.user_data["t"] = query.data.replace("reg_", "")
    await query.edit_message_text("Valor:"); return REG_VALUE
async def reg_val(update, context):
    try: context.user_data["v"] = float(update.message.text.replace(',', '.'))
    except: return REG_VALUE
    cats = db["categories"][context.user_data["t"]]; kb = []
    for i in range(0, len(cats), 2): kb.append([InlineKeyboardButton(c, callback_data=f"sc_{c}") for c in cats[i:i+2]])
    await update.message.reply_text("Categoria:", reply_markup=InlineKeyboardMarkup(kb)); return REG_CAT
async def reg_cat(update, context):
    context.user_data["c"] = update.callback_query.data.replace("sc_", "")
    kb = [[InlineKeyboardButton("⏩ Pular", callback_data="skip_d")], [InlineKeyboardButton("🔙 Voltar", callback_data="back")]]
    await update.callback_query.edit_message_text("Descrição:", reply_markup=InlineKeyboardMarkup(kb)); return REG_DESC
async def reg_fin(update, context):
    desc = update.message.text if update.message else "Manual"
    if update.callback_query and update.callback_query.data == "skip_d": desc = context.user_data["c"]
    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":context.user_data["t"], "value":context.user_data["v"], "category":context.user_data["c"], "wallet":"Manual", "description":desc, "date":get_now().strftime("%d/%m/%Y %H:%M")})
    save_db(db); update_level(); msg = update.message or update.callback_query.message
    await msg.reply_text("✅ Salvo!"); return await start(update, context)

# ================= MAIN =================
if __name__ == "__main__":
    start_keep_alive() # INICIA O FALSO SITE
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("devo", debt_cmd)); app.add_handler(CommandHandler("receber", debt_cmd)); app.add_handler(CommandHandler("sonho", dream_cmd))
    app.add_handler(CommandHandler("buscar", search_cmd))
    
    reg_h = ConversationHandler(entry_points=[CallbackQueryHandler(reg_start, pattern="^start_reg")], states={REG_TYPE:[CallbackQueryHandler(reg_type)], REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], REG_CAT:[CallbackQueryHandler(reg_cat)], REG_DESC:[MessageHandler(filters.TEXT, reg_fin), CallbackQueryHandler(reg_fin, pattern="^skip_d")]}, fallbacks=[CallbackQueryHandler(back, pattern="^back")])
    cat_h = ConversationHandler(entry_points=[CallbackQueryHandler(c_add, pattern="^c_add")], states={CAT_ADD_TYPE:[CallbackQueryHandler(c_type)], CAT_ADD_NAME:[MessageHandler(filters.TEXT, c_save)]}, fallbacks=[CallbackQueryHandler(back, pattern="^back")])
    app.add_handler(reg_h); app.add_handler(cat_h)

    cbs = [("menu_reports", menu_reports), ("rep_nospend", rep_nospend), ("rep_evo", rep_evo), ("rep_pdf", rep_pdf), ("rep_csv", rep_csv), ("rep_pie", rep_pie),
           ("menu_debts", menu_debts), ("cl_d", cl_d), ("tg_panic", tg_panic), ("menu_persona", menu_persona), ("sp_", set_persona), ("add_d", add_debt_help),
           ("roleta", roleta), ("menu_cats", menu_cats), ("menu_shop", menu_shop), ("sl_c", sl_c), ("menu_subs", menu_subs), ("menu_dreams", menu_dreams), 
           ("backup", backup), ("undo_quick", undo_quick), ("back", back), ("reg_gasto", reg_type), ("reg_ganho", reg_type), ("tg_travel", tg_travel), ("c_del", c_del), ("dc_", c_kill), ("help_search", help_search)]
    for p, f in cbs: app.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO, restricted(smart_entry)))
    print("💎 V36 FINAL RODANDO!")
    app.run_polling(drop_pending_updates=True)
