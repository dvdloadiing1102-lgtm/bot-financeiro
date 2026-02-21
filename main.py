import os
import sys
import subprocess
import time
import logging
import threading
import json
import uuid
import math
import random
import calendar
import asyncio
import io
from datetime import datetime, timedelta

# ================= 1. AUTO-REPARO =================
def install_and_restart():
    required = ["flask", "apscheduler", "python-telegram-bot", "google-generativeai>=0.7.2", "matplotlib", "reportlab", "python-dateutil", "requests"]
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade"] + required)
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except: sys.exit(1)

try:
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
except ImportError:
    install_and_restart()

# ================= 2. CONFIGURAÇÃO =================
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
import warnings
warnings.filterwarnings("ignore")

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ALLOWED_USERS", "0").split(",")[0] if os.getenv("ALLOWED_USERS") else 0)
DB_FILE = "finance_v116.json"

# ESTADOS CONVERSATION
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL, DEBT_ACTION, 
 IPTV_NAME, IPTV_PHONE, IPTV_DAY, IPTV_VAL, IPTV_EDIT_VAL, GOAL_NAME, GOAL_VAL, DEBT_INIT_VAL) = range(17)

COLORS = ['#ff9999','#66b3ff','#99ff99','#ffcc99', '#c2c2f0','#ffb3e6']
plt.style.use('dark_background')
MY_PIX_KEY = "21998121271" # SUA CHAVE PIX DA FOTO

# ================= 3. IA SETUP =================
model_ai = None
MODEL_STATUS = "IA OFF"
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        all_models = list(genai.list_models())
        valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        if valid_models:
            chosen = next((m for m in valid_models if 'flash' in m), next((m for m in valid_models if 'pro' in m), valid_models[0]))
            model_ai = genai.GenerativeModel(chosen)
            MODEL_STATUS = f"Conectado: {chosen}"
            print(f"✅ {MODEL_STATUS}")
        else: print("⚠️ Nenhum modelo disponível.")
    except Exception as e:
        print(f"❌ Erro IA: {e}"); 
        try: model_ai = genai.GenerativeModel('gemini-pro')
        except: pass

# ================= 4. BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], "shopping_list": [], "debts_v2": {},
        "categories": {"ganho": ["Salário", "Extra", "Vendas/IPTV"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa"]},
        "vip_users": {}, "config": {"panic_mode": False, "persona": "padrao"}, "reminders": [], "subscriptions": [],
        "iptv_clients": [], "goals": [], "achievements": []
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            if "iptv_clients" not in data: data["iptv_clients"] = []
            if "goals" not in data: data["goals"] = []
            if "achievements" not in data: data["achievements"] = []
            if "subscriptions" not in data: data["subscriptions"] = []
            if "reminders" not in data: data["reminders"] = []
            if "Vendas/IPTV" not in data["categories"]["ganho"]: data["categories"]["ganho"].append("Vendas/IPTV")
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= 5. UTILS & SCHEDULER =================
def get_now(): return datetime.utcnow() - timedelta(hours=3)

def calc_stats():
    gan = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'ganho')
    gas = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto')
    return (gan - gas), gas

def is_vip(user_id):
    if user_id == ADMIN_ID: return True, "👑 ADMIN"
    u = db["vip_users"].get(str(user_id))
    if u and datetime.strptime(u, "%Y-%m-%d") > get_now(): return True, "✅ VIP"
    return False, "❌ Bloqueado"

def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        if not is_vip(update.effective_user.id)[0]:
            await update.message.reply_text("🚫 VIP Necessário.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def routine_checks(context):
    now = get_now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    
    # 1. Agenda (Disparo de Lembretes)
    to_remove = []
    if "reminders" in db and db["reminders"]:
        for i, rem in enumerate(db["reminders"]):
            if rem["time"] == now_str:
                try: 
                    await context.bot.send_message(chat_id=ADMIN_ID, text=f"⏰ **AGENDA ({rem['time']})**\n\n📌 {rem['text']}", parse_mode="Markdown")
                except: pass
                to_remove.append(i)
        if to_remove:
            for index in sorted(to_remove, reverse=True): del db["reminders"][index]
            save_db(db)
    
    # 2. IPTV Cobrança
    if now.hour == 9 and now.minute == 0: await check_iptv_due(context)
    # 3. Backup
    if now.hour == 23 and now.minute == 59: await perform_auto_backup(context)
    # 4. Conquistas
    if now.minute == 30: await check_achievements(context)

async def check_iptv_due(context):
    now = get_now(); amanha = now + timedelta(days=1); clientes = []
    for c in db["iptv_clients"]:
        try:
            if int(c["day"]) == amanha.day: clientes.append(c)
        except: pass
    if clientes and ADMIN_ID:
        kb = [[InlineKeyboardButton(f"📲 {c['name']}", callback_data=f"iptv_manage_{c['id']}")] for c in clientes]
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"📺 **ALERTA IPTV:** {len(clientes)} vencendo amanhã!", reply_markup=InlineKeyboardMarkup(kb))

async def perform_auto_backup(context):
    if ADMIN_ID and os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "rb") as f: await context.bot.send_document(chat_id=ADMIN_ID, document=f, caption="🔄 Backup Diário")
        except: pass

async def check_achievements(context):
    if not ADMIN_ID: return
    new_badge = None
    if len(db["iptv_clients"]) >= 5 and "ip_baron" not in db["achievements"]:
        db["achievements"].append("ip_baron"); new_badge = "👑 **Barão do IPTV** (5+ Clientes)"
    
    saldo, _ = calc_stats()
    if saldo > 1000 and "rich_1k" not in db["achievements"]:
        db["achievements"].append("rich_1k"); new_badge = "💸 **Primeiro K** (Saldo > R$ 1.000)"
    
    if new_badge:
        save_db(db)
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🏆 **NOVA CONQUISTA DESBLOQUEADA!**\n\n{new_badge}", parse_mode="Markdown")

# ================= 6. INTERFACE =================
async def start(update, context):
    context.user_data.clear()
    saldo, gastos = calc_stats()
    uid = update.effective_user.id
    status, msg_vip = is_vip(uid)
    kb_inline = [
        [InlineKeyboardButton("📺 Gestão IPTV", callback_data="menu_iptv"), InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
        [InlineKeyboardButton("🧾 Dívidas", callback_data="menu_debts"), InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🏆 Conquistas", callback_data="menu_badges"), InlineKeyboardButton("⏰ Agenda", callback_data="menu_agenda")],
        [InlineKeyboardButton("⚙️ Configs", callback_data="menu_conf"), InlineKeyboardButton("📚 Manual", callback_data="menu_help")],
        [InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]
    if uid == ADMIN_ID: kb_inline.insert(0, [InlineKeyboardButton("👑 PAINEL DO DONO", callback_data="admin_panel")])
    kb_reply = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    
    msg = f"💎 **FINANCEIRO V116 (AGENDA+IPTV)**\n{msg_vip} | {MODEL_STATUS}\n\n💰 Saldo: **R$ {saldo:.2f}**\n📉 Gastos: R$ {gastos:.2f}"
    
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_inline), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb_reply, resize_keyboard=True), parse_mode="Markdown")
        await update.message.reply_text("⚙️ **Menu:**", reply_markup=InlineKeyboardMarkup(kb_inline))
    return ConversationHandler.END

async def back(update, context): 
    if update.callback_query: await update.callback_query.answer()
    await start(update, context)

async def cancel_op(update, context):
    await update.message.reply_text("🚫 Cancelado."); return ConversationHandler.END

# ================= METAS =================
async def menu_goals(update, context):
    saldo, _ = calc_stats()
    txt = f"🎯 **METAS FINANCEIRAS**\nSeu saldo disponível: R$ {saldo:.2f}\n\n"
    if not db["goals"]: txt += "_Nenhuma meta cadastrada._"
    else:
        for g in db["goals"]:
            prog = (saldo / g['val']) * 100 if g['val'] > 0 else 0
            if prog > 100: prog = 100
            bar = "█" * int(prog/10) + "░" * (10 - int(prog/10))
            txt += f"📌 **{g['name']}**\nR$ {g['val']:.2f}\n`[{bar}] {prog:.1f}%`\n\n"
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="goal_add"), InlineKeyboardButton("🗑️ Limpar", callback_data="goal_del")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def goal_add(update, context): await update.callback_query.edit_message_text("Nome da Meta (ex: Carro):"); return GOAL_NAME
async def goal_save_name(update, context): context.user_data["gn"] = update.message.text; await update.message.reply_text("Valor da Meta (ex: 30000):"); return GOAL_VAL
async def goal_save_val(update, context):
    try:
        v = float(update.message.text.replace(',', '.'))
        db["goals"].append({"name": context.user_data["gn"], "val": v})
        save_db(db); await update.message.reply_text("✅ Meta Salva!"); return await start(update, context)
    except: await update.message.reply_text("Erro valor."); return GOAL_VAL
async def goal_del(update, context): db["goals"] = []; save_db(db); await menu_goals(update, context)

# ================= CONQUISTAS =================
async def menu_badges(update, context):
    badges = db.get("achievements", [])
    txt = "🏆 **SUAS CONQUISTAS:**\n\n"
    mapa = {"ip_baron": "👑 **Barão do IPTV**: 5+ Clientes", "rich_1k": "💸 **Primeiro K**: Saldo > 1.000"}
    if not badges: txt += "_Ainda sem medalhas. Continue usando!_"
    else:
        for b in badges: txt += f"{mapa.get(b, '🏅 Medalha Secreta')}\n"
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")

# ================= RELATÓRIOS COMPLETOS =================
async def menu_reports(update, context): 
    kb = [
        [InlineKeyboardButton("🏆 Ranking Gastos", callback_data="rep_rank"), InlineKeyboardButton("📉 Comparativo Mês", callback_data="rep_comp")],
        [InlineKeyboardButton("🔮 Vidente IPTV", callback_data="rep_forecast"), InlineKeyboardButton("🔮 Insights", callback_data="rep_insights")],
        [InlineKeyboardButton("📝 Extrato", callback_data="rep_list"), InlineKeyboardButton("🗑️ Gerenciar", callback_data="menu_manage_trans")], 
        [InlineKeyboardButton("🍕 Pizza", callback_data="rep_pie"), InlineKeyboardButton("📈 Evolução", callback_data="rep_evo")],
        [InlineKeyboardButton("📄 PDF", callback_data="rep_pdf"), InlineKeyboardButton("📊 CSV", callback_data="rep_csv")],
        [InlineKeyboardButton("📅 Mapa", callback_data="rep_nospend"), InlineKeyboardButton("🔙 Voltar", callback_data="back")]
    ]
    await update.callback_query.edit_message_text("📊 **Relatórios Ultimate:**", reply_markup=InlineKeyboardMarkup(kb))

async def rep_rank(update, context):
    await update.callback_query.answer("Calculando...")
    m = get_now().strftime("%m/%Y")
    rank = {}
    for t in db["transactions"]:
        if t['type'] == 'gasto' and m in t['date']:
            k = t.get('description', t['category'])
            rank[k] = rank.get(k, 0) + t['value']
    sorted_rank = sorted(rank.items(), key=lambda item: item[1], reverse=True)[:5]
    txt = f"🏆 **RANKING DE VILÕES ({m})**\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, (nome, val) in enumerate(sorted_rank): txt += f"{medals[i]} **{nome}**: R$ {val:.2f}\n"
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

async def rep_comp(update, context):
    now = get_now(); m_atual = now.strftime("%m/%Y"); m_ant = (now - relativedelta(months=1)).strftime("%m/%Y")
    g_atual = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m_atual in t['date'])
    g_ant = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m_ant in t['date'])
    diff = g_atual - g_ant; icon = "🔴" if diff > 0 else "🟢"
    txt = f"📉 **COMPARATIVO**\n{m_ant}: R$ {g_ant:.2f}\n{m_atual}: R$ {g_atual:.2f}\nDiff: {icon} R$ {abs(diff):.2f}"
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

async def rep_forecast(update, context):
    now = get_now(); d7 = now + timedelta(days=7); d30 = now + timedelta(days=30); val7 = 0; val30 = 0
    for c in db["iptv_clients"]:
        try:
            dia_venc = int(c['day']); val = c.get('value', 0); prox_venc = datetime(now.year, now.month, dia_venc)
            if prox_venc < now: prox_venc += relativedelta(months=1)
            if prox_venc <= d7: val7 += val
            if prox_venc <= d30: val30 += val
        except: pass
    txt = f"🔮 **VIDENTE IPTV**\n\n7 Dias: R$ {val7:.2f}\n30 Dias: R$ {val30:.2f}"
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

async def rep_csv(update, context):
    await update.callback_query.answer("Gerando CSV...")
    with open("relatorio.csv", "w", newline='', encoding='utf-8-sig') as f:
        import csv; w = csv.writer(f, delimiter=';'); w.writerow(["Data", "Tipo", "Valor", "Categoria", "Descricao"])
        for t in db["transactions"]: w.writerow([t['date'], t['type'], str(t['value']).replace('.',','), t['category'], t.get('description', '')])
    with open("relatorio.csv", "rb") as f: await update.callback_query.message.reply_document(f)

async def rep_evo(update, context):
    await update.callback_query.answer("Gerando...")
    d, l = [], []
    for i in range(5, -1, -1):
        m = (get_now() - relativedelta(months=i)).strftime("%m/%Y")
        val = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])
        d.append(val); l.append(m[:2])
    plt.clf(); plt.figure(figsize=(6, 4)); plt.plot(l, d, marker='o', color='#00ffcc'); plt.grid(alpha=0.3); plt.title("Evolução", color="white")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close(); await update.callback_query.message.reply_photo(buf)

async def rep_nospend(update, context):
    m = get_now().strftime("%m/%Y"); dg = {int(t['date'][:2]) for t in db["transactions"] if t['type']=='gasto' and m in t['date']}
    txt = f"📅 **Mapa {m}**\n` D S T Q Q S S`\n"; 
    for d in range(1, 32):
        if d > get_now().day: break
        txt += f"{'🔴' if d in dg else '🟢'} "; txt += "\n" if d % 7 == 0 else ""
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

# ================= MÓDULO IPTV =================
async def menu_iptv(update, context):
    total = len(db["iptv_clients"]); receita = sum(c.get("value", 0) for c in db["iptv_clients"])
    msg = f"📺 **GESTOR IPTV**\nClientes: **{total}**\nReceita: **R$ {receita:.2f}**"
    kb = [[InlineKeyboardButton("➕ Novo", callback_data="iptv_add"), InlineKeyboardButton("📋 Lista", callback_data="iptv_list")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def iptv_add_start(update, context): await update.callback_query.edit_message_text("👤 **Nome:**"); return IPTV_NAME
async def iptv_save_name(update, context): context.user_data["vn"] = update.message.text; await update.message.reply_text("📱 **WhatsApp:**"); return IPTV_PHONE
async def iptv_save_phone(update, context): context.user_data["vp"] = update.message.text; await update.message.reply_text("📅 **Dia (1-31):**"); return IPTV_DAY
async def iptv_save_day(update, context):
    try: context.user_data["vd"] = int(update.message.text); await update.message.reply_text("💵 **Valor (Ex: 35.00):**"); return IPTV_VAL
    except: await update.message.reply_text("❌ Dia inválido."); return IPTV_DAY
async def iptv_save_val(update, context):
    try:
        v = float(update.message.text.replace(',', '.'))
        c = {"id": str(uuid.uuid4())[:8], "name": context.user_data["vn"], "phone": context.user_data["vp"], "day": context.user_data["vd"], "value": v}
        db["iptv_clients"].append(c); save_db(db); await update.message.reply_text(f"✅ Salvo!"); return await start(update, context)
    except: await update.message.reply_text("❌ Valor inválido."); return IPTV_VAL
async def iptv_list(update, context):
    if not db["iptv_clients"]: await update.callback_query.edit_message_text("Vazio.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_iptv")]])); return
    kb = []; sorted_clients = sorted(db["iptv_clients"], key=lambda x: int(x['day']))
    for c in sorted_clients: kb.append([InlineKeyboardButton(f"{c['day']:02d} | {c['name']} (R$ {c.get('value',0):.0f})", callback_data=f"iptv_manage_{c['id']}")])
    kb.append([InlineKeyboardButton("🔙", callback_data="menu_iptv")]); await update.callback_query.edit_message_text("📋 **Clientes:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def iptv_manage_client(update, context):
    cid = update.callback_query.data.replace("iptv_manage_", ""); client = next((c for c in db["iptv_clients"] if c["id"] == cid), None)
    if not client: await iptv_list(update, context); return
    msg = f"👤 **{client['name']}**\nVence dia {client['day']}\nPlano: R$ {client.get('value',0):.2f}"
    kb = [[InlineKeyboardButton("✅ PAGOU", callback_data=f"iptv_pay_{cid}")], [InlineKeyboardButton("💰 Cobrar", callback_data=f"iptv_msg_{cid}")], [InlineKeyboardButton("✏️ Editar", callback_data=f"iptv_edit_menu_{cid}"), InlineKeyboardButton("❌ Del", callback_data=f"iptv_kill_{cid}")], [InlineKeyboardButton("🔙", callback_data="iptv_list")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def iptv_pay_confirm(update, context):
    cid = update.callback_query.data.replace("iptv_pay_", ""); client = next((c for c in db["iptv_clients"] if c["id"] == cid), None)
    if not client: return
    val = client.get("value", 0); db["transactions"].append({"id": str(uuid.uuid4())[:8], "type": "ganho", "value": val, "category": "Vendas/IPTV", "description": f"IPTV - {client['name']}", "date": get_now().strftime("%d/%m/%Y %H:%M")}); save_db(db)
    await update.callback_query.answer(f"💰 + R$ {val}!"); await iptv_list(update, context)

async def iptv_edit_menu(update, context): 
    cid = update.callback_query.data.replace("iptv_edit_menu_", ""); kb = [[InlineKeyboardButton("Nome", callback_data="edit_name"), InlineKeyboardButton("Dia", callback_data="edit_day")], [InlineKeyboardButton("Valor", callback_data="edit_value"), InlineKeyboardButton("Zap", callback_data="edit_phone")], [InlineKeyboardButton("🔙", callback_data=f"iptv_manage_{cid}")]]
    context.user_data["edit_id"] = cid; await update.callback_query.edit_message_text("📝 Editar:", reply_markup=InlineKeyboardMarkup(kb))

async def iptv_edit_ask(update, context): context.user_data["edit_field"] = update.callback_query.data.replace("edit_", ""); await update.callback_query.edit_message_text("Novo valor:"); return IPTV_EDIT_VAL
async def iptv_edit_save(update, context):
    cid = context.user_data.get("edit_id"); field = context.user_data.get("edit_field"); val = update.message.text
    for c in db["iptv_clients"]: 
        if c["id"] == cid: 
            if field=="day": c[field]=int(val)
            elif field=="value": c[field]=float(val.replace(',','.'))
            else: c[field]=val
    save_db(db); await update.message.reply_text("✅ Feito!"); return await start(update, context)

# --- TEXTO DA FOTO (CORRIGIDO PARA O SEU PADRÃO) ---
async def iptv_gen_msg(update, context):
    cid = update.callback_query.data.replace("iptv_msg_", "")
    client = next((c for c in db["iptv_clients"] if c["id"] == cid), None)
    now = get_now()
    dia = int(client['day'])
    m = now.month + 1 if now.day > dia else now.month
    ano = now.year + 1 if m == 1 and now.month == 12 else now.year
    data_formatada = f"{dia:02d}/{m:02d}/{ano}"
    
    txt = f"""Olá querido(a) cliente {client['name']}

SUA CONTA EXPIRA EM BREVE!

Seu plano vence em:
{data_formatada}

Evite o bloqueio automático do seu sinal

Para renovar o seu plano agora, faça o
pix no seguinte pix:

Pix: {MY_PIX_KEY}

Por favor, nos envie o comprovante de
pagamento assim que possível.

É sempre um prazer te atender."""
    
    await update.callback_query.message.reply_text(f"`{txt}`", parse_mode="Markdown")
    await update.callback_query.answer()

async def iptv_kill(update, context): 
    cid = update.callback_query.data.replace("iptv_kill_", ""); db["iptv_clients"] = [c for c in db["iptv_clients"] if c["id"] != cid]; save_db(db); await update.callback_query.answer("🗑️"); await iptv_list(update, context)

# ================= RESTO =================
async def undo_quick(update, context): query = update.callback_query; await query.answer(); db["transactions"].pop() if db["transactions"] else None; save_db(db); await query.edit_message_text("Desfeito!")
async def manual_gasto_trigger(update, context): context.user_data["t"] = "gasto"; await update.message.reply_text("💸 Valor?"); return REG_VALUE
async def manual_ganho_trigger(update, context): context.user_data["t"] = "ganho"; await update.message.reply_text("💰 Valor?"); return REG_VALUE
async def reg_start(update, context): await start(update, context); return REG_TYPE
async def reg_type(update, context): context.user_data["t"] = update.callback_query.data.replace("reg_", ""); await update.callback_query.edit_message_text("Valor:"); return REG_VALUE
async def reg_val(update, context): context.user_data["v"] = float(update.message.text.replace(',', '.')); kb = [[InlineKeyboardButton(c, callback_data=f"sc_{c}") for c in db["categories"][context.user_data["t"]][i:i+2]] for i in range(0, len(db["categories"][context.user_data["t"]]), 2)]; await update.message.reply_text("Categoria:", reply_markup=InlineKeyboardMarkup(kb)); return REG_CAT
async def reg_cat(update, context): context.user_data["c"] = update.callback_query.data.replace("sc_", ""); kb = [[InlineKeyboardButton("⏩ Pular", callback_data="skip_d")]]; await update.callback_query.edit_message_text("Descrição?", reply_markup=InlineKeyboardMarkup(kb)); return REG_DESC
async def reg_fin(update, context):
    desc = context.user_data["c"] if update.callback_query else update.message.text
    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":context.user_data["t"], "value":context.user_data["v"], "category":context.user_data["c"], "description":desc, "date":get_now().strftime("%d/%m/%Y %H:%M")})
    save_db(db); msg = f"✅ Registrado!"; await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(msg); return await start(update, context)

# OUTROS MENUS
async def menu_debts(update, context): txt="🧾 Dívidas:"; kb=[[InlineKeyboardButton(f"{n}: {v}", callback_data=f"ed_{n}")] for n,v in db.get("debts_v2", {}).items()]; kb.append([InlineKeyboardButton("➕ Add", callback_data="add_p"), InlineKeyboardButton("🔙", callback_data="back")]); await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
async def add_person_start(update, context): await update.callback_query.edit_message_text("Nome:"); return DEBT_NAME
async def save_person_name(update, context): context.user_data["new_debt_name"] = update.message.text; await update.message.reply_text(f"Quanto {update.message.text} deve? (0 se nada)"); return DEBT_INIT_VAL
async def save_person_val(update, context):
    try: val = float(update.message.text.replace(',', '.')); name = context.user_data["new_debt_name"]; db["debts_v2"][name] = val; save_db(db); await update.message.reply_text("✅ Salvo!"); return await start(update, context)
    except: await update.message.reply_text("Valor inválido."); return DEBT_INIT_VAL
async def edit_debt_menu(update, context): context.user_data["dn"] = update.callback_query.data.replace("ed_", ""); kb=[[InlineKeyboardButton("➕ Emprestei", callback_data="da_add"), InlineKeyboardButton("➖ Pagou", callback_data="da_sub")], [InlineKeyboardButton("🗑️", callback_data="da_del"), InlineKeyboardButton("🔙", callback_data="menu_debts")]]; await update.callback_query.edit_message_text(f"👤 {context.user_data['dn']}", reply_markup=InlineKeyboardMarkup(kb))
async def debt_action(update, context): 
    act=update.callback_query.data; n=context.user_data["dn"] 
    if "del" in act: del db["debts_v2"][n]; save_db(db); await menu_debts(update, context); return
    context.user_data["da"] = "add" if "add" in act else "sub"; await update.callback_query.edit_message_text("Valor?"); return DEBT_VAL
async def debt_save_val(update, context): v=float(update.message.text.replace(',','.')); n=context.user_data["dn"]; v=-v if context.user_data["da"]=="sub" else v; db["debts_v2"][n]+=v; save_db(db); await update.message.reply_text("Ok!"); return await start(update, context)

async def menu_shop(update, context): l=db["shopping_list"]; txt="🛒 Lista:\n"+"\n".join(l); kb=[[InlineKeyboardButton("Limpar", callback_data="sl_c"), InlineKeyboardButton("🔙", callback_data="back")]]; await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
async def sl_c(update, context): db["shopping_list"]=[]; save_db(db); await start(update, context)
async def rep_list(update, context): t=db["transactions"][-10:]; txt="\n".join([f"{x['type']} {x['value']} ({x['description']})" for x in t]); await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]))
async def menu_manage_trans(update, context): kb=[[InlineKeyboardButton(f"🗑️ {t['value']} ({t['description']})", callback_data=f"del_tr_{t['id']}")] for t in db["transactions"][-5:]]; kb.append([InlineKeyboardButton("🔙", callback_data="menu_reports")]); await update.callback_query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))
async def delete_transaction_confirm(update, context): tid=update.callback_query.data.replace("del_tr_", ""); db["transactions"]=[t for t in db["transactions"] if t['id']!=tid]; save_db(db); await update.callback_query.answer("Apagado!"); await menu_manage_trans(update, context)
async def rep_insights(update, context): await update.callback_query.answer("Use o botão Vidente IPTV para previsão."); await menu_reports(update, context)
async def rep_pie(update, context): 
    await update.callback_query.answer("Gerando..."); cats={}; m=get_now().strftime("%m/%Y")
    for t in db["transactions"]: 
        if t['type']=='gasto' and m in t['date']: cats[t['category']]=cats.get(t['category'],0)+t['value']
    if not cats: await update.callback_query.message.reply_text("Sem dados."); return
    plt.clf(); fig, ax = plt.subplots(figsize=(6, 4)); ax.pie(cats.values(), autopct='%1.1f%%', startangle=90, colors=COLORS); ax.legend(cats.keys(), loc="best"); buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close(); await update.callback_query.message.reply_photo(buf)
async def rep_pdf(update, context): 
    c = canvas.Canvas("relatorio.pdf", pagesize=letter); c.drawString(50, 750, "EXTRATO"); y = 700
    for t in reversed(db["transactions"][-40:]): c.drawString(50, y, f"{t['date']} | R$ {t['value']:.2f} | {t['description']}"); y -= 20
    c.save(); 
    with open("relatorio.pdf", "rb") as f: await update.callback_query.message.reply_document(f)

async def menu_cats(update, context): await update.callback_query.edit_message_text("Categorias:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕", callback_data="c_add"), InlineKeyboardButton("❌", callback_data="c_del"), InlineKeyboardButton("🔙", callback_data="back")]]))
async def c_add(update, context): await update.callback_query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Gasto", callback_data="nc_gasto"), InlineKeyboardButton("Ganho", callback_data="nc_ganho")]])); return CAT_ADD_TYPE
async def c_type(update, context): context.user_data["nt"] = update.callback_query.data.replace("nc_", ""); await update.callback_query.edit_message_text("Nome:"); return CAT_ADD_NAME
async def c_save(update, context): db["categories"][context.user_data["nt"]].append(update.message.text); save_db(db); await update.message.reply_text("Ok!"); return await start(update, context)
async def c_del(update, context): kb=[[InlineKeyboardButton(c, callback_data=f"kc_gasto_{c}")] for c in db["categories"]["gasto"]]; kb.append([InlineKeyboardButton("🔙", callback_data="back")]); await update.callback_query.edit_message_text("Del:", reply_markup=InlineKeyboardMarkup(kb))
async def c_kill(update, context): _, t, n = update.callback_query.data.split("_"); db["categories"][t].remove(n); save_db(db); await update.callback_query.edit_message_text("Del!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

# ================= CONFIG / PERSONA / SUBS =================
async def menu_conf(update, context):
    p = "🔴" if db["config"]["panic_mode"] else "🟢"; persona_atual = db["config"].get("persona", "padrao").title()
    kb = [[InlineKeyboardButton(f"Pânico: {p}", callback_data="tg_panic"), InlineKeyboardButton(f"🎭 IA: {persona_atual}", callback_data="menu_persona")], [InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text("⚙️ **Configurações:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def tg_panic(update, context): db["config"]["panic_mode"] = not db["config"]["panic_mode"]; save_db(db); await menu_conf(update, context)
async def menu_persona(update, context): kb = [[InlineKeyboardButton("🧔🏿‍♂️ Julius", callback_data="sp_julius"), InlineKeyboardButton("🤡 Zoeiro", callback_data="sp_zoeiro")], [InlineKeyboardButton("👔 Padrão", callback_data="sp_padrao")], [InlineKeyboardButton("🔙", callback_data="menu_conf")]]; await update.callback_query.edit_message_text("🎭 **Personalidade da IA:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def set_persona(update, context): db["config"]["persona"] = update.callback_query.data.replace("sp_", ""); save_db(db); await update.callback_query.answer("Atualizado!"); await menu_conf(update, context)
async def menu_subs(update, context):
    subs = db.get("subscriptions", []); txt = f"🔔 **ASSINATURAS**\nTotal: **R$ {sum(float(s['val']) for s in subs):.2f}**\n\n" + "\n".join([f"• {s['name']} (Dia {s['day']}): R$ {s['val']}" for s in subs]); kb = [[InlineKeyboardButton("➕ Add (/sub)", callback_data="sub_add"), InlineKeyboardButton("🗑️ Del", callback_data="sub_del")], [InlineKeyboardButton("🔙", callback_data="menu_conf")]]; await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def sub_add_help(update, context): await update.callback_query.answer(); await update.callback_query.message.reply_text("Use:\n`/sub Netflix 55.90 15`")
async def sub_cmd(update, context): 
    try: n, v, d = context.args[0], float(context.args[1].replace(',', '.')), int(context.args[2]); db["subscriptions"].append({"name": n, "val": v, "day": d}); save_db(db); await update.message.reply_text("✅ Conta salva!")
    except: await update.message.reply_text("Erro. Use: `/sub Nome Valor Dia`")
async def sub_del_menu(update, context): db["subscriptions"] = []; save_db(db); await menu_subs(update, context)

# --- AGENDA (FIXED) ---
async def menu_agenda(update, context): 
    rems = db.get("reminders", [])
    if not rems: txt = "_Nenhum lembrete._"
    else: txt = "\n".join([f"• {r['time']}: {r['text']}" for r in rems])
    await update.callback_query.edit_message_text(f"⏰ **AGENDA:**\n\n{txt}\n\n_Para adicionar, fale: 'Me lembre de pagar X amanhã'_", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Limpar", callback_data="del_agenda_all"), InlineKeyboardButton("🔙", callback_data="back")]], parse_mode="Markdown"))
async def agenda_del(update, context): db["reminders"]=[]; save_db(db); await start(update, context)
async def menu_help(update, context): await update.callback_query.edit_message_text("Ajuda: Use o menu.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))
async def backup(update, context): 
    with open(DB_FILE, "rb") as f: await update.callback_query.message.reply_document(f)
async def admin_panel(update, context): await update.callback_query.edit_message_text("Admin", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))
async def roleta(update, context): await update.callback_query.edit_message_text("Girar", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Girar", callback_data="roleta"), InlineKeyboardButton("🔙", callback_data="back")]]))

# --- IA HANDLER CORRIGIDO ---
@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message; wait = await msg.reply_text("🧠..."); now = get_now()
    prompt = f"""SYSTEM: JSON Extractor. No chat.
    Date: {now}. Examples:
    Input: "Gastei 50 mercado" -> {{"type":"gasto", "val":50.0, "cat":"Mercado", "desc":"Mercado"}}
    Input: "Recebi 100" -> {{"type":"ganho", "val":100.0, "cat":"Extra", "desc":"Extra"}}
    Input: "Me lembre de pagar a luz dia 20 às 14h" -> {{"type":"agenda", "text":"Pagar a luz", "time":"2026-MM-20 14:00"}}
    User Input:"""
    content = [prompt]
    if msg.voice or msg.audio:
        try:
            fid = (msg.voice or msg.audio).file_id; f_obj = await context.bot.get_file(fid); f_path = f"audio_{uuid.uuid4()}.ogg"; await f_obj.download_to_drive(f_path)
            myfile = genai.upload_file(f_path); 
            while myfile.state.name == "PROCESSING": time.sleep(1); myfile = genai.get_file(myfile.name)
            content.append(myfile); content.append("Transcreva e extraia JSON.")
        except: await wait.edit_text("Erro áudio."); return
    elif msg.photo:
        f = await context.bot.get_file(msg.photo[-1].file_id); d = await f.download_as_bytearray()
        content.append({"mime_type": "image/jpeg", "data": bytes(d)}); content.append("Valor da nota?")
    else: content.append(f"{msg.text}")
    try:
        resp = model_ai.generate_content(content); t = resp.text
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(t[start:end+1])
            if data:
                if data.get('type') == 'agenda': 
                    db["reminders"].append({"text": data['text'], "time": data['time'], "chat_id": update.effective_chat.id})
                    save_db(db); await wait.edit_text(f"⏰ Agendado: {data['text']} para {data['time']}"); return
                if data.get('type') == 'mercado': db["shopping_list"].append(data['item']); save_db(db); await wait.edit_text(f"🛒 {data['item']}"); return
                if 'val' in data: 
                    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":data['type'], "value":float(data['val']), "category":data.get('cat','Geral'), "description":data.get('desc','IA'), "date":now.strftime("%d/%m/%Y %H:%M")})
                    save_db(db); await wait.edit_text(f"✅ R$ {data['val']:.2f} ({data.get('desc')})"); return
                if data.get('msg'): await wait.edit_text(data['msg']); return
        await wait.edit_text(t.replace("```json", "").replace("```", ""))
    except Exception as e: await wait.edit_text(f"Erro IA: {e}")

# ================= MAIN =================
def main():
    print("🚀 V116 AGENDA+IPTV ONLINE...")
    app_flask = Flask('')
    @app_flask.route('/')
    def home(): return "V116 OK"
    threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=10000), daemon=True).start()
    
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("cancel", cancel_op))
    app_bot.add_handler(CommandHandler("sub", sub_cmd))
    
    app_bot.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^(💸 Gasto|💰 Ganho)$"), manual_gasto_trigger)],
        states={REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], REG_CAT:[CallbackQueryHandler(reg_cat)], REG_DESC:[MessageHandler(filters.TEXT, reg_fin), CallbackQueryHandler(reg_fin, pattern="^skip_d")]},
        fallbacks=[CommandHandler("start", start)]
    ))
    
    app_bot.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_p"), CallbackQueryHandler(c_add, pattern="^c_add"), CallbackQueryHandler(debt_action, pattern="^da_")],
        states={DEBT_NAME:[MessageHandler(filters.TEXT, save_person_name)], DEBT_INIT_VAL:[MessageHandler(filters.TEXT, save_person_val)], DEBT_VAL:[MessageHandler(filters.TEXT, debt_save_val)], CAT_ADD_TYPE:[CallbackQueryHandler(c_type)], CAT_ADD_NAME:[MessageHandler(filters.TEXT, c_save)]},
        fallbacks=[CommandHandler("start", start)]
    ))

    app_bot.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(iptv_add_start, pattern="^iptv_add")],
        states={IPTV_NAME:[MessageHandler(filters.TEXT, iptv_save_name)], IPTV_PHONE:[MessageHandler(filters.TEXT, iptv_save_phone)], IPTV_DAY:[MessageHandler(filters.TEXT, iptv_save_day)], IPTV_VAL:[MessageHandler(filters.TEXT, iptv_save_val)]},
        fallbacks=[CommandHandler("start", start)]
    ))

    app_bot.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(iptv_edit_ask, pattern="^edit_")],
        states={IPTV_EDIT_VAL:[MessageHandler(filters.TEXT, iptv_edit_save)]},
        fallbacks=[CommandHandler("start", start)]
    ))

    app_bot.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_add, pattern="^goal_add")],
        states={GOAL_NAME:[MessageHandler(filters.TEXT, goal_save_name)], GOAL_VAL:[MessageHandler(filters.TEXT, goal_save_val)]},
        fallbacks=[CommandHandler("start", start)]
    ))

    cbs = [("menu_shop", menu_shop), ("menu_debts", menu_debts), ("sl_c", sl_c), ("back", start),
           ("menu_reports", menu_reports), ("rep_list", rep_list), ("rep_pie", rep_pie), ("rep_pdf", rep_pdf), ("rep_nospend", rep_nospend), ("rep_insights", rep_insights), ("rep_csv", rep_csv), ("rep_evo", rep_evo),
           ("menu_manage_trans", menu_manage_trans), ("del_tr_", delete_transaction_confirm),
           ("menu_agenda", menu_agenda), ("del_agenda_all", agenda_del),
           ("menu_cats", menu_cats), ("c_del", c_del), ("kc_", c_kill),
           ("menu_conf", menu_conf), ("tg_panic", tg_panic), ("menu_persona", menu_persona), ("sp_", set_persona), ("menu_subs", menu_subs), ("sub_add", sub_add_help), ("sub_del", sub_del_menu),
           ("roleta", roleta), ("menu_help", menu_help), ("backup", backup), ("admin_panel", admin_panel), ("undo_quick", undo_quick),
           ("ed_", edit_debt_menu), ("da_", debt_action), ("sc_", reg_cat),
           ("menu_iptv", menu_iptv), ("iptv_list", iptv_list), ("iptv_manage_", iptv_manage_client), 
           ("iptv_msg_", iptv_gen_msg), ("iptv_pay_", iptv_pay_confirm), ("iptv_kill_", iptv_kill), ("iptv_edit_menu_", iptv_edit_menu),
           ("menu_goals", menu_goals), ("goal_del", goal_del), ("menu_badges", menu_badges), ("rep_rank", rep_rank), ("rep_comp", rep_comp), ("rep_forecast", rep_forecast)]
    
    for p, f in cbs: app_bot.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, restricted(smart_entry)))
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(routine_checks, 'interval', minutes=1, args=[app_bot])
    scheduler.start()
    
    print("✅ V116 AGENDA+IPTV ONLINE!")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
