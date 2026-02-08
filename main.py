import os
import json
import logging
import uuid
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from dateutil.relativedelta import relativedelta
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Segurança (Coloque seu ID se quiser bloquear estranhos)
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip().isdigit()]

DB_FILE = "finance_v19.json"
logging.basicConfig(level=logging.INFO)

# Configuração da IA (Usando modelo PRO para compatibilidade)
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        model_ai = genai.GenerativeModel('gemini-pro')
    except:
        model_ai = None
else:
    model_ai = None

# Estados para o modo Manual (Botões)
SELECT_TYPE, VALUE_INPUT, WALLET_PICK, CAT_PICK, DESC_INPUT = range(5)

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras"]
        }, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Crédito"],
        "config": {"zoeiro_mode": False}
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

# ================= LÓGICA FINANCEIRA =================
def get_balance():
    now = datetime.now().strftime("%m/%Y")
    ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and now in t['date'])
    gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and now in t['date'])
    return ganhos - gastos, ganhos, gastos

# ================= MENU PRINCIPAL =================
async def start(update, context):
    context.user_data.clear()
    saldo, entra, sai = get_balance()
    
    kb = [
        [InlineKeyboardButton("📝 REGISTRAR (Manual)", callback_data="start_manual")],
        [InlineKeyboardButton("📊 Saldo/Gráfico", callback_data="report"), InlineKeyboardButton("🗣️ Coach IA", callback_data="ai_coach")],
        [InlineKeyboardButton("🗑️ Desfazer Último", callback_data="undo"), InlineKeyboardButton("Modo Zoeira", callback_data="toggle_mode")]
    ]
    
    txt = (f"🤖 **FINANCEIRO V19 (HÍBRIDO)**\n\n"
           f"📅 **Mês Atual:**\n📈 Entrou: R$ {entra:.2f}\n📉 Saiu: R$ {sai:.2f}\n"
           f"💰 **Saldo: R$ {saldo:.2f}**\n\n"
           f"💡 *Opções: Use os botões acima OU digite 'Gastei 50 no mercado'*")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= MODO MANUAL (BOTÕES) =================
async def start_manual(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="gasto"), InlineKeyboardButton("📈 GANHO", callback_data="ganho")]]
    await query.edit_message_text("O que vamos registrar?", reply_markup=InlineKeyboardMarkup(kb))
    return SELECT_TYPE

async def save_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data['type'] = query.data
    await query.edit_message_text(f"💰 Qual o valor do {query.data.upper()}?\n(Digite apenas números, ex: 15.50)")
    return VALUE_INPUT

async def save_value(update, context):
    try:
        val = float(update.message.text.replace(',', '.'))
        context.user_data['value'] = val
        kb = [[InlineKeyboardButton(w, callback_data=w)] for w in db['wallets']]
        await update.message.reply_text("💳 Qual carteira?", reply_markup=InlineKeyboardMarkup(kb))
        return WALLET_PICK
    except:
        await update.message.reply_text("❌ Valor inválido. Tente de novo:")
        return VALUE_INPUT

async def save_wallet(update, context):
    query = update.callback_query; await query.answer()
    context.user_data['wallet'] = query.data
    cats = db['categories'][context.user_data['type']]
    # Cria botões de 2 em 2
    kb = [cats[i:i+2] for i in range(0, len(cats), 2)]
    kb_final = [[InlineKeyboardButton(c, callback_data=c) for c in row] for row in kb]
    
    await query.edit_message_text("📂 Qual categoria?", reply_markup=InlineKeyboardMarkup(kb_final))
    return CAT_PICK

async def save_category(update, context):
    query = update.callback_query; await query.answer()
    context.user_data['category'] = query.data
    await query.edit_message_text("✍️ Digite uma descrição (ou 'ok' para pular):")
    return DESC_INPUT

async def save_finish(update, context):
    desc = update.message.text
    if desc.lower() == 'ok': desc = context.user_data['category']
    
    t = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data['type'],
        "value": context.user_data['value'],
        "category": context.user_data['category'],
        "wallet": context.user_data['wallet'],
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    db["transactions"].append(t)
    save_db(db)
    await update.message.reply_text(f"✅ Salvo via Manual!\nR$ {t['value']:.2f} - {t['description']}")
    return await start(update, context)

# ================= MODO AUTOMÁTICO (IA) =================
async def smart_entry(update, context):
    if not model_ai:
        await update.message.reply_text("⚠️ IA indisponível. Use o botão 'REGISTRAR'.")
        return

    msg = update.message
    txt_input = msg.text or "Imagem recebida"
    
    prompt = f"""
    Interprete: "{txt_input}". Retorne JSON:
    {{"type": "gasto/ganho", "value": float, "category": "Uma de: {db['categories']['gasto']}", "wallet": "Uma de: {db['wallets']}", "description": "resumo"}}
    Se não for financeiro, retorne {{"error": "true"}}
    """
    
    wait = await msg.reply_text("🧠 Processando...")
    try:
        # Tenta usar texto (Gemini Pro é mais estável que Flash em libs antigas)
        resp = model_ai.generate_content(prompt)
        data = json.loads(resp.text.replace('```json', '').replace('```', ''))
        
        if data.get("error"):
            await wait.edit_text("🤷‍♂️ Não entendi. Use o menu manual.")
            return

        t = {
            "id": str(uuid.uuid4())[:8],
            "type": data['type'],
            "value": data['value'],
            "category": data['category'],
            "wallet": data['wallet'],
            "description": data['description'],
            "date": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        db["transactions"].append(t)
        save_db(db)
        await wait.edit_text(f"✅ **IA Registrou:**\nR$ {t['value']:.2f} | {t['category']}\n({t['description']})")
        
    except Exception as e:
        await wait.edit_text(f"❌ Erro na IA. Use o botão 'REGISTRAR'.\nErro: {e}")

# ================= OUTRAS FUNÇÕES =================
async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    saldo, _, _ = get_balance()
    prompt = f"Analise saldo de R$ {saldo}. Dê dica financeira curta."
    if db["config"]["zoeiro_mode"]: prompt += " Seja zoeiro e sarcástico."
    
    try:
        resp = model_ai.generate_content(prompt)
        await query.message.reply_text(f"🧠 {resp.text}")
    except:
        await query.message.reply_text("IA dormiu.")

async def report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    gastos = [t for t in db["transactions"] if t['type'] == 'gasto' and mes in t['date']]
    cats = {}
    for g in gastos: cats[g['category']] = cats.get(g['category'], 0) + g['value']
    
    txt = "📊 **Gastos por Categoria:**\n"
    for c, v in cats.items(): txt += f"{c}: R$ {v:.2f}\n"
    
    # Gera Gráfico
    if cats:
        plt.figure(figsize=(6,4))
        plt.pie(cats.values(), labels=cats.keys(), autopct='%1.0f%%')
        plt.title(f"Gastos {mes}")
        buf = io.BytesIO()
        plt.savefig(buf, format='png'); buf.seek(0); plt.close()
        await query.message.reply_photo(buf, caption=txt)
    else:
        await query.message.reply_text("Sem dados para gráfico.")

async def undo(update, context):
    query = update.callback_query; await query.answer()
    if db["transactions"]:
        t = db["transactions"].pop()
        save_db(db)
        await query.message.reply_text(f"🗑️ Apagado: {t['description']} (R$ {t['value']})")
    else:
        await query.message.reply_text("Nada para apagar.")
    await start(update, context)

async def toggle_mode(update, context):
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db); await start(update, context)

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handler da Conversa Manual
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_manual, pattern="^start_manual$")],
        states={
            SELECT_TYPE: [CallbackQueryHandler(save_type)],
            VALUE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_value)],
            WALLET_PICK: [CallbackQueryHandler(save_wallet)],
            CAT_PICK: [CallbackQueryHandler(save_category)],
            DESC_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_finish)]
        },
        fallbacks=[CommandHandler('cancel', start)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    
    # Handlers Soltos
    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
    app.add_handler(CallbackQueryHandler(undo, pattern="^undo$"))
    app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
    
    # Handler IA (Pega texto que sobrar)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_entry))
    
    print("Bot V19 Híbrido Iniciado!")
    app.run_polling(drop_pending_updates=True)
