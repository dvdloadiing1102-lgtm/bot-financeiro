import os
import json
import logging
import uuid
import io
import csv
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta # pip install python-dateutil

import google.generativeai as genai
import matplotlib
matplotlib.use('Agg') # Backend não-interativo para servidores
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# ⚠️ SEGURANÇA: Coloque seu ID do Telegram aqui para bloquear estranhos
# Mande uma mensagem pro bot, ele vai printar seu ID no log se não estiver aqui.
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "0").split(",")] 
# Exemplo no render env: ALLOWED_USERS = 12345678,87654321

DB_FILE = "finance_v18_ultimate.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Flash é mais rápido e barato, suporta imagem e texto
    model_ai = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.warning("GEMINI_API_KEY faltando!")

# ================= BANCO DE DADOS & MIGRATION =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas"]
        }, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Cartão Crédito"],
        "budgets": {"Alimentação": 800, "Lazer": 300}, # Metas mensais
        "achievements": [], # Conquistas desbloqueadas
        "fixed": [], 
        "config": {"zoeiro_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            # Migration simples para garantir chaves novas
            for k in default:
                if k not in data: data[k] = default[k]
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= DECORATOR DE SEGURANÇA =================
def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USERS and 0 not in ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await update.message.reply_text(f"⛔ Acesso negado. Seu ID: {user_id}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ================= LÓGICA FINANCEIRA =================
def calculate_balance(target_date=None):
    if not target_date: target_date = datetime.now()
    mes_str = target_date.strftime("%m/%Y")
    
    ganhos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'ganho')
    gastos_fixos = sum(f['value'] for f in db["fixed"] if f['type'] == 'gasto')
    
    trans_ganhos = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho' and mes_str in t['date'])
    trans_gastos = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_str in t['date'])
    
    saldo_mes = (ganhos_fixos + trans_ganhos) - (gastos_fixos + trans_gastos)
    
    # Saldo acumulado (simplificado)
    total_in = sum(t['value'] for t in db["transactions"] if t['type'] == 'ganho')
    total_out = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto')
    saldo_total = total_in - total_out
    
    return saldo_mes, (ganhos_fixos + trans_ganhos), (gastos_fixos + trans_gastos), saldo_total

def check_achievements(update):
    new_unlocks = []
    # Exemplo: Mão de Vaca (Gasto < 50 em Lazer no mes) - Lógica simplificada
    if len(db["transactions"]) > 10 and "Iniciante" not in db["achievements"]:
        db["achievements"].append("Iniciante")
        new_unlocks.append("🥉 Iniciante: Registrou 10 transações!")
    
    # Adicione mais lógicas aqui
    return new_unlocks

def check_budget_alert(category, value_added):
    limit = db["budgets"].get(category, 0)
    if limit == 0: return None
    
    mes = datetime.now().strftime("%m/%Y")
    gastos_cat = sum(t['value'] for t in db["transactions"] 
                     if t['category'] == category and t['type'] == 'gasto' and mes in t['date'])
    
    pct = (gastos_cat / limit) * 100
    if pct >= 100: return f"🚨 **ALERTA:** Você estourou o orçamento de {category} ({pct:.1f}%)!"
    elif pct >= 80: return f"⚠️ **Aviso:** Você já usou {pct:.1f}% do orçamento de {category}."
    return None

# ================= PROCESSAMENTO IA (TEXTO E IMAGEM) =================
async def process_smart_entry(update, context):
    user_msg = update.message
    
    prompt = """
    Atue como um assistente financeiro (JSON Parser).
    Analise o texto ou imagem fornecida. Extraia os dados da transação.
    
    Regras:
    1. Identifique: type ('gasto', 'ganho', 'transferencia'), value (float), category (classifique na melhor possível), wallet (qual carteira/banco), description (resumo), date (DD/MM/YYYY), installments (int, 1 se não parcelado).
    2. Se for 'transferencia', 'wallet' é a origem e coloque o destino na 'description'.
    3. Categorias existentes: Alimentação, Transporte, Lazer, Mercado, Casa, Saúde, Compras, Salário, Extra.
    4. Carteiras existentes: Nubank, Itaú, Dinheiro, Inter, Cartão Crédito.
    5. Se não identificar carteira, assuma 'Nubank'. Se não identificar categoria, assuma 'Outros'.
    6. Se o usuário falar em parcelas (ex: "em 10x"), defina 'installments'.
    7. Converta moedas para BRL se necessário.
    
    Retorne APENAS um JSON válido neste formato, sem Markdown:
    {"type": "gasto", "value": 50.00, "category": "Alimentação", "wallet": "Nubank", "description": "Lanche", "date": "08/02/2026", "installments": 1}
    
    Se não for financeiro, retorne: {"error": "Não entendi"}
    """

    content = []
    content.append(prompt)
    
    # Se tiver imagem
    if user_msg.photo:
        wait_msg = await user_msg.reply_text("👁️ Analisando imagem...")
        file_id = user_msg.photo[-1].file_id
        file = await context.bot.get_file(file_id)
        file_bytes = await file.download_as_bytearray()
        
        # Converte para formato aceito pelo Gemini
        image_part = {"mime_type": "image/jpeg", "data": file_bytes}
        content.append(image_part)
        content.append("Extraia os dados deste comprovante/nota.")
    else:
        wait_msg = await user_msg.reply_text("🧠 Processando texto...")
        content.append(f"Texto do usuário: {user_msg.text}")

    try:
        response = model_ai.generate_content(content)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned_text)
        
        if data.get("error"):
            await wait_msg.edit_text("❌ Não identifiquei uma transação válida.")
            return

        # Processamento de Parcelas
        installments = data.get("installments", 1)
        base_date = datetime.strptime(data.get("date", datetime.now().strftime("%d/%m/%Y")), "%d/%m/%Y")
        total_val = data['value']
        
        # Se for parcelado, divide o valor (ou mantém se a IA entender que o valor é da parcela)
        # Vamos assumir que o valor informado é o total da compra, a menos que IA diga o contrario.
        # Simplificação: IA retorna valor da parcela se detectar "10x de 50".
        
        msgs_out = []
        
        for i in range(installments):
            eff_date = base_date + relativedelta(months=i)
            desc_final = data['description']
            if installments > 1:
                desc_final += f" ({i+1}/{installments})"
            
            t = {
                "id": str(uuid.uuid4())[:8],
                "type": data['type'],
                "value": total_val if installments == 1 else (total_val / installments if "x de" not in user_msg.text.lower() else total_val), 
                # Ajuste fino: Se o usuário diz "100 reais em 2x", é 50/mes. Se diz "2x de 50", é 50/mes. 
                # A IA geralmente retorna o valor unitário se o prompt for bom, vamos confiar no valor da IA por enquanto.
                "category": data['category'],
                "wallet": data['wallet'],
                "description": desc_final,
                "date": eff_date.strftime("%d/%m/%Y %H:%M"),
                "user_id": user_msg.from_user.id
            }
            db["transactions"].append(t)
        
        save_db(db)
        
        # Feedback
        res_txt = f"✅ **Registrado!**\n{data['type'].upper()}: R$ {data['value']:.2f}\n📂 {data['category']} | 💳 {data['wallet']}\n📝 {data['description']}"
        if installments > 1: res_txt += f"\n📅 Parcelado em {installments}x"
        
        # Alertas
        alert = check_budget_alert(data['category'], data['value'])
        if alert: res_txt += f"\n\n{alert}"
        
        # Conquistas
        unlocks = check_achievements(update)
        for u in unlocks: res_txt += f"\n\n🏆 **CONQUISTA:** {u}"
        
        await wait_msg.edit_text(res_txt, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Erro IA: {e}")
        await wait_msg.edit_text(f"❌ Erro ao processar. Tente manual.")

# ================= MENU PRINCIPAL =================
@restricted
async def start(update, context):
    context.user_data.clear()
    saldo_mes, in_mes, out_mes, saldo_total = calculate_balance()
    
    zoeiro = "🤡 ON" if db["config"]["zoeiro_mode"] else "🤖 OFF"
    
    kb = [
        [InlineKeyboardButton("🗣️ Dica da IA", callback_data="ai_coach"), InlineKeyboardButton("🎲 Roleta", callback_data="roleta")],
        [InlineKeyboardButton("🔍 Raio-X Mês", callback_data="full_report"), InlineKeyboardButton("📉 Evolução", callback_data="chart_evolution")],
        [InlineKeyboardButton("💾 Backup", callback_data="backup"), InlineKeyboardButton(f"Zoeira: {zoeiro}", callback_data="toggle_mode")],
        [InlineKeyboardButton("❌ Limpar Último", callback_data="del_last")]
    ]
    
    txt = (f"🚀 **FINANCEIRO V18 ULTIMATE**\n\n"
           f"📅 **Mês Atual:**\n🟢 R$ {in_mes:.2f} | 🔴 R$ {out_mes:.2f}\n"
           f"⚖️ **Saldo Mês:** R$ {saldo_mes:.2f}\n"
           f"💰 **Patrimônio Total:** R$ {saldo_total:.2f}\n\n"
           f"💡 *Dica: Envie texto ('Gastei 10...') ou foto para registrar.*")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ================= FUNCIONALIDADES EXTRAS =================
async def roleta_russa(update, context):
    import random
    query = update.callback_query; await query.answer()
    if random.random() > 0.5:
        msg = "😈 **COMPRA!** Você merece, a vida é curta e o boleto é longo."
    else:
        msg = "😇 **NÃO COMPRA!** Vai sobrar mês no fim do dinheiro."
    await query.message.reply_text(msg)

async def chart_evolution(update, context):
    query = update.callback_query; await query.answer()
    
    # Agrupar por mês (últimos 6 meses)
    data_map = {}
    today = datetime.now()
    for i in range(5, -1, -1):
        d = today - relativedelta(months=i)
        key = d.strftime("%m/%Y")
        data_map[key] = 0

    for t in db["transactions"]:
        m = t['date'][:7] # MM/YYYY
        if m in data_map and t['type'] == 'gasto':
            data_map[m] += t['value']

    plt.figure(figsize=(10, 5))
    plt.plot(list(data_map.keys()), list(data_map.values()), marker='o', color='r', linestyle='-')
    plt.title("Evolução de Gastos (6 meses)")
    plt.grid(True)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    await query.message.reply_photo(photo=buf)

async def backup_data(update, context):
    query = update.callback_query; await query.answer()
    with open(DB_FILE, 'rb') as f:
        await query.message.reply_document(f, caption=f"💾 Backup {datetime.now()}")

async def del_last(update, context):
    query = update.callback_query; await query.answer()
    if not db["transactions"]:
        await query.message.reply_text("Nada para apagar.")
        return
    
    t = db["transactions"].pop()
    save_db(db)
    await query.message.reply_text(f"🗑️ Apagado: {t['description']} (R$ {t['value']})")
    await start(update, context)

async def ai_coach(update, context):
    query = update.callback_query; await query.answer()
    saldo, t_in, t_out, total = calculate_balance()
    
    prompt = "Aja como um consultor financeiro."
    if db["config"]["zoeiro_mode"]:
        prompt += " Seja sarcástico, faça piadas sobre pobreza e gastos inúteis. Use gírias brasileiras."
    else:
        prompt += " Seja formal, direto e analítico."

    # Resumo das maiores categorias
    mes = datetime.now().strftime("%m/%Y")
    gastos = [t for t in db["transactions"] if t['type'] == 'gasto' and mes in t['date']]
    cats = {}
    for g in gastos: cats[g['category']] = cats.get(g['category'], 0) + g['value']
    top_cat = max(cats, key=cats.get) if cats else "Nada"
    
    prompt += f" Dados: Saldo Mês: {saldo}, Gastos: {t_out}, Maior gasto: {top_cat}. Dê uma dica curta."
    
    msg = await query.message.reply_text("🧠 Pensando...")
    try:
        resp = model_ai.generate_content(prompt)
        await msg.edit_text(resp.text)
    except:
        await msg.edit_text("A IA tirou folga.")

async def toggle_mode(update, context):
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db)
    await start(update, context)

async def full_report(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    trans = [t for t in db["transactions"] if mes in t['date'] and t['type'] == 'gasto']
    cats = {}
    for t in trans: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    
    msg = f"🔍 **RAIO-X {mes}**\n"
    sorted_cats = sorted(cats.items(), key=lambda x:x[1], reverse=True)
    
    for c, v in sorted_cats:
        # Barra de progresso visual
        bar = "▓" * int(v / 100)
        msg += f"\n🔸 {c}: R$ {v:.2f}\n   {bar}"
        
    await query.message.reply_text(msg, parse_mode="Markdown")

# ================= MAIN =================
if __name__ == "__main__":
    if not TOKEN:
        print("ERRO: TELEGRAM_TOKEN não configurado!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Comandos
        app.add_handler(CommandHandler("start", start))
        
        # Callbacks do Menu
        app.add_handler(CallbackQueryHandler(ai_coach, pattern="^ai_coach$"))
        app.add_handler(CallbackQueryHandler(roleta_russa, pattern="^roleta$"))
        app.add_handler(CallbackQueryHandler(chart_evolution, pattern="^chart_evolution$"))
        app.add_handler(CallbackQueryHandler(backup_data, pattern="^backup$"))
        app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
        app.add_handler(CallbackQueryHandler(del_last, pattern="^del_last$"))
        app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$"))
        
        # Handler Inteligente (Texto e Foto)
        # Pega qualquer texto que NÃO seja comando, e qualquer foto
        app.add_handler(MessageHandler(
            (filters.TEXT & ~filters.COMMAND) | filters.PHOTO, 
            restricted(process_smart_entry)
        ))
        
        print(f"Bot V18 Ultimate iniciado! Monitorando ID(s): {ALLOWED_USERS}")
        app.run_polling(drop_pending_updates=True)
