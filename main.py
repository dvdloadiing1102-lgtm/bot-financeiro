import os
import json
import logging
import uuid
import io
import csv
import random
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import google.generativeai as genai
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip().isdigit()]
DB_FILE = "finance_v23_god_mode.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= IA AUTO-CONFIG =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        chosen = next((m for m in models if 'flash' in m), next((m for m in models if 'gemini-pro' in m), None))
        if chosen: model_ai = genai.GenerativeModel(chosen)
    except: pass

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas"]
        }, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Crédito"],
        "budgets": {"Alimentação": 800, "Lazer": 300, "Mercado": 1000},
        "subscriptions": [], # Nova: Lista de assinaturas
        "shopping_list": [], # Nova: Lista de compras
        "achievements": [],
        "fixed": [], 
        "config": {"persona": "padrao", "panic_mode": False} # Nova: Persona e Panico
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            for k in default: 
                if k not in data: data[k] = default[k]
            # Migration deep merge
            if "persona" not in data["config"]: data["config"]["persona"] = "padrao"
            if "panic_mode" not in data["config"]: data["config"]["panic_mode"] = False
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= ESTADOS =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_CAT, REG_DESC, 
 NEW_CAT_TYPE, NEW_CAT_NAME, SHOP_VAL) = range(8)

# ================= LÓGICA & HELPERS =================
def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Acesso Negado."); return
        return await func(update, context, *args, **kwargs)
    return wrapped

def calc_stats():
    now = datetime.now(); mes = now.strftime("%m/%Y")
    ganhos = sum(t['value'] for t in db["transactions"] if t['type']=='ganho' and mes in t['date'])
    gastos = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and mes in t['date'])
    
    # Previsão (Vidente)
    dia_hoje = now.day; ultimo_dia = (now.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
    media_diaria = gastos / dia_hoje if dia_hoje > 0 else 0
    previsao = gastos + (media_diaria * (ultimo_dia - dia_hoje))
    
    return (ganhos - gastos), ganhos, gastos, previsao

def get_persona_prompt():
    p = db["config"]["persona"]
    base = "Atue como consultor financeiro."
    if db["config"]["panic_mode"]:
        return base + " MODO PÂNICO ATIVADO. O usuário está quebrado. Seja EXTREMAMENTE RIGOROSO. Proíba qualquer gasto supérfluo. Grite se precisar."
    
    personas = {
        "padrao": "Seja profissional e direto.",
        "julius": "Você é o Julius (Pai do Chris). Obcecado por economia. Se o gasto for fútil, dê bronca. Calcule quantas horas de trabalho custou.",
        "primo": "Você é o Primo Rico. Fale sobre 'mindset', 'aportes', 'passivos' e 'cortar o cafezinho'.",
        "mae": "Você é uma Mãe Brasileira cuidadosa. 'Na volta a gente compra'. Pergunte se ele realmente precisa disso.",
        "zoeiro": "Seja um comediante sarcástico. Faça piada da pobreza e das escolhas ruins do usuário."
    }
    return base + " " + personas.get(p, personas["padrao"])

# ================= IA INTELIGENTE =================
@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message
    
    # Prompt Turbinado
    prompt = f"""
    {get_persona_prompt()}
    Analise o input. Se for financeiro, extraia JSON.
    1. Campos: type (gasto/ganho/transferencia), value (float), category, wallet, description, installments (int), date (DD/MM/YYYY), currency (str).
    2. Se for moeda estrangeira (USD, EUR), converta para BRL (use taxa aproximada atual) e avise na descrição.
    3. Se o usuário mandar uma LISTA de coisas, tente somar ou criar uma entrada única resumida.
    4. Se Panico ativado e gasto for "Lazer" ou "Compras", adicione campo "warning": "true".
    
    Input: "{msg.text or 'FOTO'}"
    Retorno JSON: {{"type": "...", "value": 0.0, "category": "...", "wallet": "...", "description": "...", "installments": 1, "warning": "false"}}
    Se não for financeiro (ex: conversa), responda como o personagem apenas (texto puro, sem JSON).
    """
    
    wait = await msg.reply_text("🧠...")
    try:
        content = [prompt]
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id)
            d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": d})
        
        resp = model_ai.generate_content(content)
        txt = resp.text.strip()
        
        # Tenta parsear JSON
        if "{" in txt and "}" in txt:
            json_str = txt[txt.find("{"):txt.rfind("}")+1]
            data = json.loads(json_str)
            
            # Lógica de registro
            inst = data.get("installments", 1)
            val = data['value']
            base_date = datetime.now()
            
            for i in range(inst):
                d_date = base_date + relativedelta(months=i)
                desc = data['description'] + (f" ({i+1}/{inst})" if inst > 1 else "")
                
                db["transactions"].append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "gasto" if data['type']=='transferencia' else data['type'],
                    "value": val / inst if inst > 1 else val,
                    "category": data['category'],
                    "wallet": data['wallet'],
                    "description": desc,
                    "date": d_date.strftime("%d/%m/%Y %H:%M"),
                    "user_id": msg.from_user.id,
                    "user_name": msg.from_user.first_name,
                    "location": None # Será preenchido se tiver handler de location
                })
            save_db(db)
            
            res = f"✅ **{data['category']}** | R$ {val:.2f}\n📝 {data['description']}"
            if data.get("warning") == "true": res += "\n\n🚨 **ALERTA DE PÂNICO:** Você não devia ter comprado isso!"
            await wait.edit_text(res)
        else:
            # Apenas conversa do personagem
            await wait.edit_text(txt)
            
    except Exception as e:
        await wait.edit_text(f"Erro: {e}")

# ================= MENU PRINCIPAL =================
@restricted
async def start(update, context):
    context.user_data.clear()
    saldo, ganho, gasto, prev = calc_stats()
    
    # Status Icons
    persona_icon = {"julius": "😠", "primo": "🥃", "mae": "👵", "zoeiro": "🤡", "padrao": "🤖"}[db["config"]["persona"]]
    panic_icon = "🚨 ON" if db["config"]["panic_mode"] else "✅ OFF"
    
    kb = [
        [InlineKeyboardButton(f"{persona_icon} Persona", callback_data="menu_persona"), InlineKeyboardButton(f"Pânico: {panic_icon}", callback_data="toggle_panic")],
        [InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop"), InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")],
        [InlineKeyboardButton("📝 Manual", callback_data="start_reg"), InlineKeyboardButton("📉 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🔮 Vidente", callback_data="vidente"), InlineKeyboardButton("👩‍❤️‍👨 Casal", callback_data="report_couple")]
    ]
    
    msg = (f"⚡ **V23 GOD MODE** ⚡\n\n"
           f"💰 Saldo: **R$ {saldo:.2f}**\n"
           f"📉 Gastos: R$ {gasto:.2f}\n"
           f"🔮 Previsão Fim Mês: R$ -{prev:.2f} (se continuar assim)\n\n"
           f"💡 *IA com personalidade {db['config']['persona'].upper()} ativa.*")
    
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= SHOPPING LIST (NOVO) =================
async def menu_shop(update, context):
    query = update.callback_query; await query.answer()
    lista = db["shopping_list"]
    txt = "**🛒 Lista de Compras:**\n\n" + ("\n".join([f"▫️ {i}" for i in lista]) if lista else "*(Vazia)*")
    txt += "\n\nPara adicionar, digite: `/add leite`"
    
    kb = [[InlineKeyboardButton("✅ Finalizar Compra", callback_data="shop_finish"), InlineKeyboardButton("🗑️ Limpar", callback_data="shop_clear")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_shop_item(update, context):
    item = " ".join(context.args)
    if item:
        db["shopping_list"].append(item); save_db(db)
        await update.message.reply_text(f"➕ Adicionado: {item}")
    else: await update.message.reply_text("Use: /add item")

async def shop_finish(update, context):
    query = update.callback_query; await query.answer()
    if not db["shopping_list"]: return await query.message.reply_text("Lista vazia!")
    await query.edit_message_text("💰 Qual foi o valor total da compra?")
    return SHOP_VAL

async def shop_save(update, context):
    try:
        val = float(update.message.text.replace(',', '.'))
        desc = "Compra Mercado: " + ", ".join(db["shopping_list"])
        db["transactions"].append({
            "id": str(uuid.uuid4())[:8], "type": "gasto", "value": val, "category": "Mercado",
            "wallet": "Nubank", "description": desc[:100], "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "user_id": update.message.from_user.id
        })
        db["shopping_list"] = [] # Limpa
        save_db(db)
        await update.message.reply_text("✅ Compra registrada e lista limpa!")
        return await start(update, context)
    except: await update.message.reply_text("Valor inválido."); return SHOP_VAL

async def shop_clear(update, context):
    db["shopping_list"] = []; save_db(db)
    await start(update, context)

# ================= ASSINATURAS (NOVO) =================
async def menu_subs(update, context):
    query = update.callback_query; await query.answer()
    subs = db["subscriptions"] # Ex: [{"name": "Netflix", "val": 55}]
    
    txt = "**🔔 Assinaturas Recorrentes:**\n"
    total = 0
    for s in subs:
        txt += f"📺 {s['name']}: R$ {s['val']}\n"
        total += s['val']
    txt += f"\n**Total Fixo: R$ {total:.2f}**\nUse `/sub Netflix 55.90` para adicionar."
    
    kb = [[InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_sub(update, context):
    try:
        args = context.args
        val = float(args[-1].replace(',', '.'))
        name = " ".join(args[:-1])
        db["subscriptions"].append({"name": name, "val": val})
        save_db(db)
        await update.message.reply_text("✅ Assinatura salva!")
    except: await update.message.reply_text("Use: /sub Nome Valor")

# ================= PERSONALIDADES & PÂNICO =================
async def menu_persona(update, context):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("😠 Julius", callback_data="set_julius"), InlineKeyboardButton("🥃 Primo Rico", callback_data="set_primo")],
        [InlineKeyboardButton("👵 Mãe", callback_data="set_mae"), InlineKeyboardButton("🤡 Zoeiro", callback_data="set_zoeiro")],
        [InlineKeyboardButton("🤖 Padrão", callback_data="set_padrao"), InlineKeyboardButton("🔙 Voltar", callback_data="start")]
    ]
    await query.edit_message_text("🎭 **Escolha quem vai cuidar do seu dinheiro:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def set_persona(update, context):
    query = update.callback_query; await query.answer()
    p = query.data.replace("set_", "")
    db["config"]["persona"] = p; save_db(db)
    await start(update, context)

async def toggle_panic(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["panic_mode"] = not db["config"]["panic_mode"]
    save_db(db)
    state = "ATIVADO 🚨" if db["config"]["panic_mode"] else "DESATIVADO ✅"
    await query.message.reply_text(f"🛑 MODO PÂNICO {state}")
    await start(update, context)

# ================= RELATÓRIOS ESPECIAIS =================
async def vidente(update, context):
    query = update.callback_query; await query.answer()
    _, _, _, prev = calc_stats()
    
    msg = f"🔮 **Bola de Cristal Financeira** 🔮\n\n"
    if prev > 1500: msg += f"💀 Você vai gastar aprox **R$ {prev:.2f}** esse mês. ESTAMOS FERRADOS."
    elif prev > 800: msg += f"⚠️ Previsão de **R$ {prev:.2f}**. Segura a onda."
    else: msg += f"✨ Previsão de **R$ {prev:.2f}**. Tá tranquilo, pode comprar um chiclete."
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="start")]]), parse_mode="Markdown")

async def report_couple(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    users = {}
    
    for t in db["transactions"]:
        if t['type'] == 'gasto' and mes in t['date']:
            uid = t.get('user_name', 'Desconhecido')
            users[uid] = users.get(uid, 0) + t['value']
            
    txt = "👩‍❤️‍👨 **DR Financeira (Gastos por Pessoa):**\n\n"
    for u, v in users.items(): txt += f"👤 {u}: R$ {v:.2f}\n"
    
    if len(users) > 1:
        v_total = sum(users.values())
        txt += f"\nTotal: R$ {v_total:.2f}. "
        
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="start")]]), parse_mode="Markdown")

async def menu_reports(update, context):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("📊 Pizza", callback_data="chart_pie"), InlineKeyboardButton("📉 Evolução", callback_data="chart_evo")],
        [InlineKeyboardButton("📅 No Spend Days", callback_data="no_spend"), InlineKeyboardButton("📄 PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("🔙", callback_data="start")]
    ]
    await query.edit_message_text("📊 **Central de Relatórios:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def no_spend_chart(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    dias_com_gasto = set()
    for t in db["transactions"]:
        if t['type']=='gasto' and mes in t['date']:
            dias_com_gasto.add(int(t['date'][:2]))
            
    # Calendario visual
    txt = f"📅 **No Spend Challenge ({mes})**\n\n"
    txt += "DOM SEG TER QUA QUI SEX SAB\n"
    
    # Lógica simples de calendário visual (ajuste conforme necessidade)
    hoje = datetime.now().day
    for d in range(1, 32):
        if d > hoje: break
        mark = "💀" if d in dias_com_gasto else "✅"
        txt += f"{d:02}{mark} "
        if d % 7 == 0: txt += "\n"
        
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="start")]]))

# ================= FUNÇÕES CLÁSSICAS (V22) =================
# ... (PDF, CSV, Manual, Gráficos - Mantidos simplificados para caber) ...
async def export_pdf(update, context):
    query = update.callback_query; await query.answer()
    path = "/tmp/rel.pdf" if os.name != 'nt' else "rel.pdf"
    c = canvas.Canvas(path, pagesize=letter)
    c.drawString(100, 750, "Extrato V23 God Mode"); c.save()
    with open(path, 'rb') as f: await query.message.reply_document(f)

async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    cats = {}
    for t in db["transactions"]:
        if t['type']=='gasto' and mes in t['date']: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    if not cats: await query.message.reply_text("Sem dados."); return
    plt.figure(figsize=(6,4)); plt.pie(cats.values(), labels=cats.keys(), autopct='%1.1f%%')
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)

async def start_reg(update, context): # Manual simplificado
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="reg_gasto"), InlineKeyboardButton("Ganho", callback_data="reg_ganho")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb)); return REG_TYPE

async def reg_type(update, context):
    context.user_data["t_t"] = query = update.callback_query.data.split("_")[1]
    await query.edit_message_text("Valor:"); return REG_VALUE
async def reg_val(update, context):
    context.user_data["t_v"] = float(update.message.text.replace(',', '.'))
    await update.message.reply_text("Categoria:"); return REG_CAT
async def reg_cat(update, context):
    context.user_data["t_c"] = update.message.text
    db["transactions"].append({"id":str(uuid.uuid4())[:8], "type":context.user_data["t_t"], "value":context.user_data["t_v"], "category":context.user_data["t_c"], "wallet":"Manual", "description":"Manual", "date":datetime.now().strftime("%d/%m/%Y %H:%M")})
    save_db(db); await update.message.reply_text("Salvo!"); return await start(update, context)
async def cancel(update, context): await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    if not TOKEN: print("SEM TOKEN")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Comandos
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("add", add_shop_item))
        app.add_handler(CommandHandler("sub", add_sub))
        
        # Conversa Compra
        shop_h = ConversationHandler(
            entry_points=[CallbackQueryHandler(shop_finish, pattern="shop_finish")],
            states={SHOP_VAL: [MessageHandler(filters.TEXT, shop_save)]},
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        app.add_handler(shop_h)
        
        # Conversa Manual (Simples)
        reg_h = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_reg, pattern="start_reg")],
            states={REG_TYPE:[CallbackQueryHandler(reg_type)], REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], REG_CAT:[MessageHandler(filters.TEXT, reg_cat)]},
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        app.add_handler(reg_h)

        # Menus
        pats = [("menu_shop", menu_shop), ("shop_clear", shop_clear), ("menu_subs", menu_subs), 
                ("menu_persona", menu_persona), ("set_", set_persona), ("toggle_panic", toggle_panic),
                ("vidente", vidente), ("report_couple", report_couple), ("menu_reports", menu_reports),
                ("no_spend", no_spend_chart), ("export_pdf", export_pdf), ("chart_", chart_pie)]
        
        for p, f in pats: app.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
        
        # IA (Texto e Foto)
        app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, restricted(smart_entry)))
        
        print("🤖 V23 GOD MODE RODANDO!")
        app.run_polling(drop_pending_updates=True)
