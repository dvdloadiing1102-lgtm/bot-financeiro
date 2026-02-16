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
DB_FILE = "finance_v102.json"

(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL, DEBT_ACTION) = range(9)

COLORS = ['#ff9999','#66b3ff','#99ff99','#ffcc99', '#c2c2f0','#ffb3e6']
plt.style.use('dark_background')

# ================= 3. IA SETUP (AUTO-DISCOVERY) =================
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
        print(f"❌ Erro listar modelos: {e}"); 
        try: model_ai = genai.GenerativeModel('gemini-pro')
        except: pass

# ================= 4. BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], "shopping_list": [], "debts_v2": {},
        "categories": {"ganho": ["Salário", "Extra"], "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa"]},
        "vip_users": {}, "config": {"panic_mode": False, "persona": "padrao"}, "reminders": [], "subscriptions": [],
        "goals": {}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            if "config" not in data: data["config"] = {"panic_mode": False, "persona": "padrao"}
            if "persona" not in data["config"]: data["config"]["persona"] = "padrao"
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= 5. UTILS =================
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

async def check_reminders(context):
    now_str = get_now().strftime("%Y-%m-%d %H:%M")
    to_remove = []
    if "reminders" in db and db["reminders"]:
        for i, rem in enumerate(db["reminders"]):
            if rem["time"] == now_str:
                try: await context.bot.send_message(chat_id=rem["chat_id"], text=f"⏰ **LEMBRETE!**\n\n📌 {rem['text']}", parse_mode="Markdown")
                except: pass
                to_remove.append(i)
        if to_remove:
            for index in sorted(to_remove, reverse=True): del db["reminders"][index]
            save_db(db)

# ================= 6. INTERFACE =================
async def start(update, context):
    context.user_data.clear(); saldo, gastos = calc_stats(); uid = update.effective_user.id
    status, msg_vip = is_vip(uid)
    kb_inline = [
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop")],
        [InlineKeyboardButton("🧾 Dívidas/Pessoas", callback_data="menu_debts"), InlineKeyboardButton("📊 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🎲 Roleta", callback_data="roleta"), InlineKeyboardButton("⏰ Agenda", callback_data="menu_agenda")],
        [InlineKeyboardButton("⚙️ Configs", callback_data="menu_conf"), InlineKeyboardButton("📚 Manual", callback_data="menu_help")],
        [InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]
    if uid == ADMIN_ID: kb_inline.insert(0, [InlineKeyboardButton("👑 PAINEL DO DONO", callback_data="admin_panel")])
    kb_reply = [["💸 Gasto", "💰 Ganho"], ["📊 Relatórios", "👛 Saldo"]]
    
    msg = f"💎 **FINANCEIRO V102 (SMART QUERY)**\n{msg_vip} | {MODEL_STATUS}\n\n💰 Saldo: **R$ {saldo:.2f}**\n📉 Gastos: R$ {gastos:.2f}"
    
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

async def undo_quick(update, context):
    query = update.callback_query; await query.answer()
    if db["transactions"]: db["transactions"].pop(); save_db(db); await query.edit_message_text("🗑️ Desfeito!")
    else: await query.edit_message_text("Nada para desfazer.")

# --- MANUAL COM DESCRIÇÃO ---
async def manual_gasto_trigger(update, context): context.user_data["t"] = "gasto"; await update.message.reply_text("💸 Valor?"); return REG_VALUE
async def manual_ganho_trigger(update, context): context.user_data["t"] = "ganho"; await update.message.reply_text("💰 Valor?"); return REG_VALUE
async def reg_start(update, context): await start(update, context); return REG_TYPE
async def reg_type(update, context): context.user_data["t"] = update.callback_query.data.replace("reg_", ""); await update.callback_query.edit_message_text("Valor:"); return REG_VALUE
async def reg_val(update, context): 
    try: context.user_data["v"] = float(update.message.text.replace(',', '.')); cats = db["categories"][context.user_data["t"]]
    except: return REG_VALUE
    kb = [[InlineKeyboardButton(c, callback_data=f"sc_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await update.message.reply_text("Categoria:", reply_markup=InlineKeyboardMarkup(kb)); return REG_CAT
async def reg_cat(update, context): 
    context.user_data["c"] = update.callback_query.data.replace("sc_", "")
    kb = [[InlineKeyboardButton("⏩ Pular", callback_data="skip_d")]]
    await update.callback_query.edit_message_text("📝 Qual a descrição? (Ex: Uber, Mercado Assaí, etc)\n\nOu clique em Pular.", reply_markup=InlineKeyboardMarkup(kb))
    return REG_DESC
async def reg_fin(update, context):
    if update.callback_query and update.callback_query.data == "skip_d":
        desc = context.user_data["c"]
    else:
        desc = update.message.text
        
    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":context.user_data["t"], "value":context.user_data["v"], "category":context.user_data["c"], "description":desc, "date":get_now().strftime("%d/%m/%Y %H:%M")})
    save_db(db)
    msg = f"✅ Registrado!\nR$ {context.user_data['v']:.2f} em {context.user_data['c']} ({desc})"
    if update.callback_query: await update.callback_query.edit_message_text(msg)
    else: await update.message.reply_text(msg)
    return await start(update, context)

# --- DÍVIDAS ---
async def menu_debts(update, context):
    debts = db.get("debts_v2", {}); txt = "🧾 **DÍVIDAS:**\n"; kb = []
    for n, v in debts.items(): kb.append([InlineKeyboardButton(f"✏️ {n}: R$ {v:.2f}", callback_data=f"ed_{n}")])
    kb.append([InlineKeyboardButton("➕ Add", callback_data="add_p"), InlineKeyboardButton("🔙", callback_data="back")])
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def add_person_start(update, context): await update.callback_query.edit_message_text("Nome:"); return DEBT_NAME
async def save_person_name(update, context): n = update.message.text; db["debts_v2"][n] = 0.0; save_db(db); await update.message.reply_text("✅ Salvo!"); return await start(update, context)
async def edit_debt_menu(update, context):
    n = update.callback_query.data.replace("ed_", ""); context.user_data["dn"] = n
    kb = [[InlineKeyboardButton("➕ Emprestei", callback_data="da_add"), InlineKeyboardButton("➖ Pagou", callback_data="da_sub")], [InlineKeyboardButton("🗑️ Excluir", callback_data="da_del"), InlineKeyboardButton("🔙", callback_data="menu_debts")]]
    await update.callback_query.edit_message_text(f"👤 {n}", reply_markup=InlineKeyboardMarkup(kb))
async def debt_action(update, context):
    act = update.callback_query.data; n = context.user_data.get("dn")
    if "del" in act: del db["debts_v2"][n]; save_db(db); await menu_debts(update, context); return
    context.user_data["da"] = "add" if "add" in act else "sub"; await update.callback_query.edit_message_text("Valor?"); return DEBT_VAL
async def debt_save_val(update, context):
    try: v = float(update.message.text.replace(',', '.')); n = context.user_data.get("dn"); v = -v if context.user_data["da"] == "sub" else v; db["debts_v2"][n] += v; save_db(db); await update.message.reply_text("✅ Atualizado!")
    except: pass
    return await start(update, context)

async def menu_shop(update, context):
    l = db["shopping_list"]; txt = "**🛒 LISTA:**\n" + ("_Vazia_" if not l else "\n".join([f"• {i}" for i in l]))
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="sl_c"), InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def sl_c(update, context): db["shopping_list"] = []; save_db(db); await start(update, context)

# --- RELATÓRIOS ---
async def menu_reports(update, context): 
    kb = [
        [InlineKeyboardButton("🔮 Insights e Previsão", callback_data="rep_insights")],
        [InlineKeyboardButton("📝 Extrato", callback_data="rep_list"), InlineKeyboardButton("🗑️ Gerenciar", callback_data="menu_manage_trans")], 
        [InlineKeyboardButton("🍕 Pizza", callback_data="rep_pie"), InlineKeyboardButton("📈 Evolução", callback_data="rep_evo")],
        [InlineKeyboardButton("📄 PDF", callback_data="rep_pdf"), InlineKeyboardButton("📊 CSV", callback_data="rep_csv")], 
        [InlineKeyboardButton("📅 Mapa", callback_data="rep_nospend"), InlineKeyboardButton("🔙 Voltar", callback_data="back")]
    ]
    await update.callback_query.edit_message_text("📊 **Relatórios Avançados:**", reply_markup=InlineKeyboardMarkup(kb))

async def rep_list(update, context): 
    trans = db["transactions"][-15:]
    if not trans: await update.callback_query.edit_message_text("📭 Vazio.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]])); return
    txt = "📝 **Últimos 15 Lançamentos:**\n\n"
    for t in reversed(trans): 
        icon = '🔴' if str(t['type']).lower()=='gasto' else '🟢'
        desc = t.get('description', '')
        desc_str = f" - {desc}" if desc and desc != t['category'] else ""
        txt += f"{icon} {t['date'][:10]} | R$ {t['value']:.2f}\n🏷️ {t['category']}{desc_str}\n\n"
    await update.callback_query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

async def menu_manage_trans(update, context):
    trans = db["transactions"][-5:]
    if not trans: await update.callback_query.edit_message_text("📭 Vazio.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]])); return
    txt = "🗑️ **Excluir Recentes:**\n\n"
    kb = []
    for t in reversed(trans):
        icon = "🔴" if str(t['type']).lower() == 'gasto' else "🟢"
        kb.append([InlineKeyboardButton(f"🗑️ {icon} R$ {t['value']:.2f} ({t['category']})", callback_data=f"del_tr_{t['id']}")])
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_reports")])
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_transaction_confirm(update, context):
    tid = update.callback_query.data.replace("del_tr_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db); await update.callback_query.answer("🗑️ Apagado!"); await menu_manage_trans(update, context)

async def rep_insights(update, context):
    await update.callback_query.answer("Calculando previsões...")
    now = get_now(); m = now.strftime("%m/%Y")
    gastos_mes = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])
    ganhos_mes = sum(t['value'] for t in db["transactions"] if t['type']=='ganho' and m in t['date'])
    dias_passados = now.day; dias_no_mes = calendar.monthrange(now.year, now.month)[1]
    media_diaria = gastos_mes / dias_passados if dias_passados > 0 else 0
    previsao_gastos = media_diaria * dias_no_mes
    saldo_previsto = ganhos_mes - previsao_gastos

    txt = f"🔮 **INSIGHTS INTELIGENTES ({m})**\n\n📉 **Média Diária:** R$ {media_diaria:.2f}/dia\n⚠️ **Previsão de Gastos (Fim do Mês):** R$ {previsao_gastos:.2f}\n💰 **Previsão de Saldo Final:** R$ {saldo_previsto:.2f}\n\n"
    if saldo_previsto < 0: txt += "🚨 **ALERTA:** Você vai fechar o mês no **VERMELHO**. Reduza os custos imediatamente!"
    elif saldo_previsto < (ganhos_mes * 0.1): txt += "⚠️ **AVISO:** Vai sobrar pouco. Cuidado."
    else: txt += "✅ **ÓTIMO CAMINHO:** Mantendo esse padrão, vai sobrar dinheiro!"
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_reports")]]), parse_mode="Markdown")

async def rep_pie(update, context):
    await update.callback_query.answer("Gerando...")
    cats = {}; m = get_now().strftime("%m/%Y")
    for t in db["transactions"]:
        if t['type'] == 'gasto' and m in t['date']: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    if not cats: await update.callback_query.message.reply_text("Sem dados."); return
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.pie(cats.values(), autopct='%1.1f%%', startangle=90, colors=COLORS)
    ax.legend(cats.keys(), loc="best", bbox_to_anchor=(1, 0.5)); ax.set_title(f"Gastos {m}", color='white')
    buf = io.BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0); plt.close()
    await update.callback_query.message.reply_photo(buf)

async def rep_pdf(update, context):
    c = canvas.Canvas("relatorio.pdf", pagesize=letter); c.drawString(50, 750, "EXTRATO FINANCEIRO"); y = 700
    for t in reversed(db["transactions"][-40:]):
        if y < 50: break
        c.drawString(50, y, f"{t['date']} | {t['type'].upper()} | R$ {t['value']:.2f} | {t['category']} | {t.get('description', '')}"); y -= 15
    c.save()
    with open("relatorio.pdf", "rb") as f: await update.callback_query.message.reply_document(f)

async def rep_csv(update, context):
    await update.callback_query.answer("Gerando CSV...")
    with open("relatorio.csv", "w", newline='', encoding='utf-8-sig') as f:
        import csv; w = csv.writer(f, delimiter=';')
        w.writerow(["Data", "Tipo", "Valor", "Categoria", "Descricao"])
        for t in db["transactions"]: w.writerow([t['date'], t['type'], str(t['value']).replace('.',','), t['category'], t.get('description', '')])
    with open("relatorio.csv", "rb") as f: await update.callback_query.message.reply_document(f)

async def rep_evo(update, context):
    await update.callback_query.answer("Gerando Gráfico..."); d, l = [], []
    for i in range(5, -1, -1): 
        m = (get_now() - relativedelta(months=i)).strftime("%m/%Y")
        d.append(sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and m in t['date'])); l.append(m[:2])
    plt.figure(figsize=(6, 4)); plt.plot(l, d, marker='o', color='#00ffcc'); plt.grid(alpha=0.3); plt.title("Evolução 6 Meses", color="white")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close(); await update.callback_query.message.reply_photo(buf)

async def rep_nospend(update, context):
    m = get_now().strftime("%m/%Y"); dg = {int(t['date'][:2]) for t in db["transactions"] if t['type']=='gasto' and m in t['date']}
    txt = f"📅 **Mapa {m}**\n` D S T Q Q S S`\n"; 
    for d in range(1, 32): 
        if d > get_now().day: break
        txt += f"{'🔴' if d in dg else '🟢'} "; txt+= "\n" if d%7==0 else ""
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_reports")]]), parse_mode="Markdown")

# --- MENUS DE SUPORTE ---
async def menu_cats(update, context):
    kb = [[InlineKeyboardButton("➕ Criar", callback_data="c_add"), InlineKeyboardButton("❌ Del", callback_data="c_del")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text("Categorias:", reply_markup=InlineKeyboardMarkup(kb))
async def c_add(update, context): kb = [[InlineKeyboardButton("Gasto", callback_data="nc_gasto"), InlineKeyboardButton("Ganho", callback_data="nc_ganho")]]; await update.callback_query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb)); return CAT_ADD_TYPE
async def c_type(update, context): context.user_data["nt"] = update.callback_query.data.replace("nc_", ""); await update.callback_query.edit_message_text("Nome:"); return CAT_ADD_NAME
async def c_save(update, context): t = context.user_data["nt"]; n = update.message.text; db["categories"][t].append(n); save_db(db); await update.message.reply_text("Criada!"); return await start(update, context)
async def c_del(update, context):
    kb = []; [kb.append([InlineKeyboardButton(c, callback_data=f"kc_gasto_{c}")]) for c in db["categories"]["gasto"]]
    kb.append([InlineKeyboardButton("🔙", callback_data="back")]); await update.callback_query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))
async def c_kill(update, context):
    _, t, n = update.callback_query.data.split("_"); db["categories"][t].remove(n); save_db(db); await update.callback_query.edit_message_text("Apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

async def menu_conf(update, context):
    p = "🔴" if db["config"]["panic_mode"] else "🟢"; 
    persona_atual = db["config"].get("persona", "padrao").title()
    kb = [[InlineKeyboardButton(f"Pânico: {p}", callback_data="tg_panic"), InlineKeyboardButton(f"🎭 IA: {persona_atual}", callback_data="menu_persona")], 
          [InlineKeyboardButton("🔔 Assinaturas Fixas", callback_data="menu_subs")], 
          [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text("⚙️ **Configurações:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def tg_panic(update, context): db["config"]["panic_mode"] = not db["config"]["panic_mode"]; save_db(db); await menu_conf(update, context)

async def menu_persona(update, context):
    kb = [[InlineKeyboardButton("🧔🏿‍♂️ Julius", callback_data="sp_julius"), InlineKeyboardButton("🤡 Zoeiro", callback_data="sp_zoeiro")], 
          [InlineKeyboardButton("👔 Padrão", callback_data="sp_padrao")], 
          [InlineKeyboardButton("🔙 Voltar", callback_data="menu_conf")]]
    await update.callback_query.edit_message_text("🎭 **Personalidade da IA:**\n\nEscolha como quer que o robô te responda:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def set_persona(update, context):
    db["config"]["persona"] = update.callback_query.data.replace("sp_", "")
    save_db(db); await update.callback_query.answer("Persona Atualizada!"); await menu_conf(update, context)

async def roleta(update, context):
    res = "😈 **COMPRA!** (Só se vive uma vez)" if random.random() > 0.5 else "😇 **NÃO COMPRA!** (Foco na meta!)"
    kb = [[InlineKeyboardButton("🔄 Girar", callback_data="roleta")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_agenda(update, context):
    rems = db.get("reminders", []); txt = "⏰ **AGENDA:**\n" + "\n".join([f"• {r['time']}: {r['text']}" for r in rems])
    kb = [[InlineKeyboardButton("🗑️ Limpar", callback_data="del_agenda_all")], [InlineKeyboardButton("🔙", callback_data="back")]]
    await update.callback_query.edit_message_text(txt + "\n\n_Dica: Peça 'Me lembre de pagar a luz amanhã'_", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def agenda_del(update, context): db["reminders"] = []; save_db(db); await update.callback_query.answer("Limpo!"); await start(update, context)

async def menu_subs(update, context):
    subs = db.get("subscriptions", []); txt = f"🔔 **ASSINATURAS**\nTotal: **R$ {sum(float(s['val']) for s in subs):.2f}**\n\n"
    if subs: txt += "\n".join([f"• {s['name']} (Dia {s['day']}): R$ {s['val']}" for s in subs])
    kb = [[InlineKeyboardButton("➕ Add (/sub)", callback_data="sub_add"), InlineKeyboardButton("🗑️ Del", callback_data="sub_del")], [InlineKeyboardButton("🔙", callback_data="menu_conf")]]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
async def sub_add_help(update, context): await update.callback_query.answer(); await update.callback_query.message.reply_text("Use:\n`/sub Netflix 55.90 15`")
async def sub_cmd(update, context):
    try: n, v, d = context.args[0], float(context.args[1].replace(',', '.')), int(context.args[2]); db["subscriptions"].append({"name": n, "val": v, "day": d}); save_db(db); await update.message.reply_text("✅ Conta salva!")
    except: await update.message.reply_text("Erro. Use: `/sub Nome Valor Dia`")
async def sub_del_menu(update, context): db["subscriptions"] = []; save_db(db); await menu_subs(update, context)

async def dream_cmd(update, context):
    try: v = float(context.args[-1]); await update.message.reply_text(f"🛌 Meta ajustada para: R$ {v}")
    except: pass

async def menu_help(update, context): await update.callback_query.edit_message_text("📚 **Manual de IA:**\n\n- 'Gastei 50 de Uber'\n- 'Adicionar leite na lista'\n- 'Quanto gastei de ifood esse mês?'\n- 'Dicas financeiras'", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]), parse_mode="Markdown")
async def backup(update, context): 
    with open(DB_FILE, "rb") as f: await update.callback_query.message.reply_document(f)
async def admin_panel(update, context): await update.callback_query.edit_message_text("Admin", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))
async def gen_key(update, context): pass
async def ask_key(update, context): pass
async def redeem_key(update, context): pass

# --- IA HANDLER (COM CONSULTA INTELIGENTE E PERSONA) ---
@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message; wait = await msg.reply_text("🧠 Processando..."); now = get_now()
    
    # 1. Configura a Persona
    persona = db["config"].get("persona", "padrao")
    persona_inst = ""
    if persona == "julius": 
        persona_inst = "Você é o Julius de 'Todo Mundo Odeia o Chris'. Você é extremamente pão duro. Se o usuário consultar gastos ou registrar gastos, dê uma bronca, reclame do valor, e diga o que você faria com esse dinheiro ou quanto de desconto pediria."
    elif persona == "zoeiro": 
        persona_inst = "Você é um robô extremamente irônico, sarcástico e zoeiro. Ao responder consultas de gastos, tire muito sarro da cara do usuário, dê puxões de orelha humilhantes se ele gastou com besteira, e chame ele de mão de vaca ou burguês safado."
    else: 
        persona_inst = "Você é um consultor financeiro profissional e amigável. Dê respostas diretas e organizadas."

    # 2. Puxa os gastos do MÊS ATUAL para a IA ler
    m_str = now.strftime("%m/%Y")
    current_tx = [{"valor": t["value"], "categoria": t["category"], "descricao": t.get("description", "")} for t in db["transactions"] if t["type"] == "gasto" and m_str in t["date"]]
    tx_json = json.dumps(current_tx, ensure_ascii=False)

    try:
        prompt = f"""AGORA: {now}. {persona_inst}
        
        HISTÓRICO DE GASTOS DO USUÁRIO DESTE MÊS (Para responder consultas):
        {tx_json}

        Responda APENAS neste formato JSON:
        - Para Mercado: {{"type":"mercado", "item":"nome_do_item"}}
        - Para Registrar Gasto/Ganho: {{"type":"gasto", "val":50.50, "cat":"Transporte", "desc":"Uber para casa"}} (campo desc é obrigatório).
        - Para Consulta de Gastos (ex: 'quanto gastei de ifood?' ou 'quanto gastei de transporte?'): Leia o HISTÓRICO DE GASTOS acima, calcule a soma exata dos valores que correspondem à pesquisa (categoria ou descrição), e retorne: {{"type":"conversa", "msg":"[Total gasto] + [Sua reação/bronca baseada na sua persona!]"}}
        - Para Bate-Papo/Conselhos: {{"type":"conversa", "msg":"Sua resposta no tom da sua persona."}}"""
        
        content = [prompt]
        if msg.voice or msg.audio:
            try:
                fid = (msg.voice or msg.audio).file_id; f_obj = await context.bot.get_file(fid); f_path = f"audio_{uuid.uuid4()}.ogg"; await f_obj.download_to_drive(f_path)
                myfile = genai.upload_file(f_path)
                while myfile.state.name == "PROCESSING": time.sleep(1); myfile = genai.get_file(myfile.name)
                content.append(myfile)
            except: await wait.edit_text("⚠️ Erro no áudio. Tente digitar."); return
        elif msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id); d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": bytes(d)})
        else: content.append(f"User: {msg.text}")
            
        resp = model_ai.generate_content(content)
        t = resp.text; data = None
        if "{" in t: data = json.loads(t[t.find("{"):t.rfind("}")+1])
        if 'f_path' in locals() and os.path.exists(f_path): os.remove(f_path)
        
        if data:
            if data.get('type') == 'mercado': db["shopping_list"].append(data['item']); save_db(db); await wait.edit_text(f"🛒 **Mercado:** {data['item']}", parse_mode="Markdown"); return
            if 'val' in data: 
                desc = data.get('desc', data.get('cat', 'IA'))
                db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":data['type'], "value":float(data['val']), "category":data.get('cat','Geral'), "description":desc, "date":now.strftime("%d/%m/%Y %H:%M")})
                save_db(db); await wait.edit_text(f"✅ Registrado: R$ {data['val']:.2f}\n🏷️ {data.get('cat')} - {desc}", parse_mode="Markdown"); return
            if data.get('msg'): await wait.edit_text(data['msg'], parse_mode="Markdown"); return
        await wait.edit_text(t)
    except Exception as e: await wait.edit_text(f"⚠️ Erro IA: {str(e)[:100]}")

# ================= 9. MAIN =================
def main():
    print("🚀 Iniciando Bot V102 (SMART QUERY)...")
    app_flask = Flask('')
    @app_flask.route('/')
    def home(): return "Bot V102 Online"
    threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=10000), daemon=True).start()
    
    app_bot = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers Comandos
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("cancel", cancel_op))
    app_bot.add_handler(CommandHandler("sub", sub_cmd))
    app_bot.add_handler(CommandHandler("sonho", dream_cmd))
    
    # Handler Manual
    app_bot.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^(💸 Gasto|💰 Ganho)$"), manual_gasto_trigger)],
        states={REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], REG_CAT:[CallbackQueryHandler(reg_cat)], REG_DESC:[MessageHandler(filters.TEXT, reg_fin), CallbackQueryHandler(reg_fin, pattern="^skip_d")]},
        fallbacks=[CommandHandler("start", start)]
    ))
    
    # Handler Dívidas e Categorias
    app_bot.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_p"), CallbackQueryHandler(c_add, pattern="^c_add")],
        states={DEBT_NAME:[MessageHandler(filters.TEXT, save_person_name)], DEBT_VAL:[MessageHandler(filters.TEXT, debt_save_val)], CAT_ADD_TYPE:[CallbackQueryHandler(c_type)], CAT_ADD_NAME:[MessageHandler(filters.TEXT, c_save)]},
        fallbacks=[CommandHandler("start", start)]
    ))
    
    # Callbacks
    cbs = [("menu_shop", menu_shop), ("menu_debts", menu_debts), ("sl_c", sl_c), ("back", start),
           ("menu_reports", menu_reports), ("rep_list", rep_list), ("rep_pie", rep_pie), ("rep_pdf", rep_pdf), ("rep_nospend", rep_nospend), ("rep_insights", rep_insights), ("rep_csv", rep_csv), ("rep_evo", rep_evo),
           ("menu_manage_trans", menu_manage_trans), ("del_tr_", delete_transaction_confirm),
           ("menu_agenda", menu_agenda), ("del_agenda_all", agenda_del),
           ("menu_cats", menu_cats), ("c_del", c_del), ("kc_", c_kill),
           ("menu_conf", menu_conf), ("tg_panic", tg_panic), ("menu_persona", menu_persona), ("sp_", set_persona), ("menu_subs", menu_subs), ("sub_add", sub_add_help), ("sub_del", sub_del_menu),
           ("roleta", roleta), ("menu_help", menu_help), ("backup", backup), ("admin_panel", admin_panel), ("undo_quick", undo_quick),
           ("ed_", edit_debt_menu), ("da_", debt_action), ("sc_", reg_cat)]
    
    for p, f in cbs: app_bot.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, restricted(smart_entry)))
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, 'interval', minutes=1, args=[app_bot])
    scheduler.start()
    
    print("✅ V102 SMART QUERY ONLINE!")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
