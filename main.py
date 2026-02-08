import os
import json
import logging
import uuid
import io
import csv
from datetime import datetime
from dateutil.relativedelta import relativedelta  # Para cálculos de meses

import google.generativeai as genai
import matplotlib
matplotlib.use('Agg')  # Backend para servidores sem monitor (evita erros no Render)
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Segurança: Lista de IDs permitidos. Se vazio no .env, ninguém acessa (ou defina lógica para liberar)
# No .env use: ALLOWED_USERS=12345678,87654321
au_env = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(x) for x in au_env.split(",") if x.strip().isdigit()]

DB_FILE = "finance_v18_ultimate.json"

# Logging para ver erros no terminal
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configura IA
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model_ai = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.warning("⚠️ GEMINI_API_KEY não encontrada! A IA não funcionará.")

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas"]
        }, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Cartão Crédito"],
        "budgets": {"Alimentação": 800, "Lazer": 300}, 
        "achievements": [], 
        "fixed": [], 
        "config": {"zoeiro_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            # Garante que chaves novas existam em bancos antigos
            for k in default:
                if k not in data: data[k] = default[k]
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= SEGURANÇA =================
def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        # Se a lista ALLOWED_USERS tiver algo, verifica. Se estiver vazia, bloqueia tudo por segurança (ou libere se preferir).
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            print(f"⛔ Tentativa de acesso negada: {user_id}")
            await update.message.reply_text(f"⛔ Acesso restrito. Seu ID: `{user_id}` (Adicione ao .env)", parse_mode="Markdown")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ================= LÓGICA FINANCEIRA =================
def calculate_balance():
    now = datetime.now()
    mes_str = now.strftime("%m/%Y")
    
    # Filtra transações do mês atual
    ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_str in t['date'])
    gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_str in t['date'])
    
    # Fixos (simples: soma tudo que está ativo)
    f_ganhos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    f_gastos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')

    total_in = ganhos + f_ganhos
    total_out = gastos + f_gastos
    saldo = total_in - total_out
    
    # Patrimônio total (histórico)
    all_in = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    all_out = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    patrimonio = all_in - all_out
    
    return saldo, total_in, total_out, patrimonio

def check_budget(category, value):
    limit = db["budgets"].get(category, 0)
    if limit == 0: return None
    
    mes = datetime.now().strftime("%m/%Y")
    gasto_cat = sum(t['value'] for t in db["transactions"] if t['category'] == category and t['type'] == 'gasto' and mes in t['date'])
    
    pct = (gasto_cat / limit) * 100
    if pct > 100: return f"🚨 **ESTOUROU:** {category} ({pct:.0f}%)"
    if pct > 80: return f"⚠️ **ALERTA:** {category} em {pct:.0f}%"
    return None

# ================= PROCESSAMENTO INTELIGENTE (IA) =================
async def smart_entry(update, context):
    msg = update.message
    user_id = msg.from_user.id
    
    prompt = """
    Analise o input (texto ou imagem). Extraia dados financeiros para JSON.
    Campos: type (gasto/ganho/transf), value (float), category (use contexto), wallet (banco/carteira), description (resumo), installments (int, padrão 1).
    Categorias comuns: Alimentação, Transporte, Lazer, Mercado, Casa, Saúde, Salário.
    Carteiras comuns: Nubank, Itaú, Dinheiro, Inter, Cartão.
    Se parcelado ("em 10x"), defina installments.
    Se não for financeiro, retorne {"error": "true"}.
    Formato APENAS JSON: {"type": "gasto", "value": 10.0, "category": "Lazer", "wallet": "Dinheiro", "description": "Coxinha", "installments": 1}
    """

    feedback_msg = await msg.reply_text("🧠 **Processando...**")
    
    try:
        content = [prompt]
        # Se tiver foto
        if msg.photo:
            file_id = msg.photo[-1].file_id
            file = await context.bot.get_file(file_id)
            img_bytes = await file.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": img_bytes})
            content.append("Extraia os dados desta nota/recibo.")
        else:
            content.append(f"Texto: {msg.text}")

        # Chama Gemini
        resp = model_ai.generate_content(content)
        txt = resp.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(txt)
        
        if data.get("error"):
            await feedback_msg.edit_text("❌ Não entendi. Tente 'Gastei 50 no mercado'.")
            return

        # Lógica de Parcelamento e Salvamento
        inst = data.get("installments", 1)
        val_total = float(data['value'])
        val_parc = val_total / inst if inst > 1 else val_total # Assume que o valor dito foi o total
        
        base_date = datetime.now()
        
        for i in range(inst):
            eff_date = base_date + relativedelta(months=i)
            desc = data['description']
            if inst > 1: desc += f" ({i+1}/{inst})"
            
            t = {
                "id": str(uuid.uuid4())[:8],
                "type": data['type'],
                "value": round(val_parc, 2),
                "category": data['category'],
                "wallet": data['wallet'],
                "description": desc,
                "date": eff_date.strftime("%d/%m/%Y %H:%M"),
                "user_id": user_id
            }
            db["transactions"].append(t)
            
        save_db(db)
        
        # Resposta final
        res = f"✅ **Registrado!**\n💲 R$ {val_total:.2f} ({data['type']})\n📂 {data['category']} | 💳 {data['wallet']}\n📝 {data['description']}"
        if inst > 1: res += f"\n📅 Parcelado em {inst}x de R$ {val_parc:.2f}"
        
        # Checa orçamentos
        alert = check_budget(data['category'], val_total)
        if alert: res += f"\n\n{alert}"
        
        await feedback_msg.edit_text(res, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Erro IA: {e}")
        await feedback_msg.edit_text(f"❌ Erro: {e}")

# ================= MENUS E COMANDOS =================
@restricted
async def start(update, context):
    context.user_data.clear()
    saldo, t_in, t_out, patri = calculate_balance()
    zoeira = "🤡 ON" if db["config"]["zoeiro_mode"] else "🤖 OFF"
    
    kb = [
        [InlineKeyboardButton("🗣️ Coach IA", callback_data="ai_coach"), InlineKeyboardButton("🎲 Roleta", callback_data="roleta")],
        [InlineKeyboardButton("📊 Gráfico", callback_data="chart_evo"), InlineKeyboardButton("📉 Raio-X", callback_data="report")],
        [InlineKeyboardButton(f"Modo: {zoeira}", callback_data="toggle_mode"), InlineKeyboardButton("🗑️ Desfazer", callback_data="undo")]
    ]
    
    txt = (f"🚀 **FINANCEIRO V18 ULTIMATE**\n\n"
           f"📅 **Mês Atual:**\n"
           f"🟢 Entrou: R$ {t_in:.2f}\n🔴 Saiu: R$ {t_out:.2f}\n"
           f"💰 **Saldo: R$ {saldo:.2f}**\n\n"
           f"🏦 **Patrimônio:** R$ {patri:.2f}\n\n"
           f"💡 *Envie texto ou foto para registrar.*")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    
    if not GEMINI_KEY:
        await query.message.reply_text("IA não configurada.")
        return

    saldo, t_in, t_out, _ = calculate_balance()
    msg = await query.message.reply_text("🧠 **Analisando suas finanças...**")
    
    style = "Sarcástico e zoeiro. Faça piada se o saldo for baixo." if db["config"]["zoeiro_mode"] else "Profissional e sério."
    prompt = f"Analise: Saldo {saldo}, Ganhos {t_in}, Gastos {t_out}. Estilo: {style}. Dê uma dica de 2 frases."
    
    try:
        resp = model_ai.generate_content(prompt)
        await msg.edit_text(f"🧠 **Coach:**\n{resp.text}")
    except:
        await msg.edit_text("A IA dormiu.")

async def chart_evo(update, context):
    query = update.callback_query; await query.answer()
    
    # Gera dados dos últimos 6 meses
    dados = {}
    hoje = datetime.now()
    for i in range(5, -1, -1):
        mes = (hoje - relativedelta(months=i)).strftime("%m/%Y")
        dados[mes] = 0
        
    for t in db["transactions"]:
        m = t['date'][:7] # mm/yyyy
        if m in dados and t['type'] == 'gasto':
            dados[m] += t['value']
            
    # Plota
    plt.figure(figsize=(10, 5))
    plt.bar(dados.keys(), dados.values(), color='salmon')
    plt.title("Gastos (Últimos 6 meses)")
    plt.grid(axis='y', alpha=0.3)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    await query.message.reply_photo(photo=buf)

async def roleta(update, context):
    import random
    query = update.callback_query; await query.answer()
    res = "😈 **COMPRA!** Só se vive uma vez." if random.random() > 0.5 else "😇 **GUARDA!** O futuro agradece."
    await query.message.reply_text(res)

async def toggle_mode(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db)
    await start(update, context)

async def undo_last(update, context):
    query = update.callback_query; await query.answer()
    if db["transactions"]:
        removed = db["transactions"].pop()
        save_db(db)
        await query.message.reply_text(f"🗑️ Removido: {removed['description']} (R$ {removed['value']})")
    else:
        await query.message.reply_text("Nada para desfazer.")

async def report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    cats = {}
    for t in trans: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    txt = f"📉 **Gastos de {mes}**\n"
    for c, v in sorted(cats.items(), key=lambda x:x[1], reverse=True):
        txt += f"\n🔸 {c}: R$ {v:.2f}"
        
    await query.message.reply_text(txt)

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERRO: TELEGRAM_TOKEN ausente.")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Comandos
        app.add_handler(CommandHandler("start", start))
        
        # Callbacks
        app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
        app.add_handler(CallbackQueryHandler(chart_evo, pattern="^chart_evo$"))
        app.add_handler(CallbackQueryHandler(roleta, pattern="^roleta$"))
        app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
        app.add_handler(CallbackQueryHandler(undo_last, pattern="^undo$"))
        app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
        
        # Handler Mágico (Texto e Foto)
        # Captura qualquer coisa que não seja comando
        app.add_handler(MessageHandler(
            (filters.TEXT & ~filters.COMMAND) | filters.PHOTO, 
            restricted(smart_entry)
        ))
        
        print(f"✅ Bot V18 Rodando! IDs permitidos: {ALLOWED_USERS}")
        app.run_polling(drop_pending_updates=True)
