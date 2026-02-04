import os
import sys
import json
import logging
import uuid
import threading
import io
import csv
import random
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- AUTO-INSTALAÇÃO ---
try:
    import httpx
    import matplotlib
    matplotlib.use('Agg') 
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    print("⚠️ Instalando dependências...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx", "matplotlib", "reportlab"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 
DB_FILE = "finance_v4_zoeiro.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= ROASTS (MODO ZOEIRO) =================
ROASTS = {
    "gasto_generico": [
        "💸 Parabéns, mais um passo rumo ao nome sujo!",
        "💸 O agiota curtiu esse lançamento.",
        "💸 Pobre não tem um dia de paz mesmo...",
        "💸 Se continuar assim, vai morar debaixo da ponte.",
        "💸 Comprou de novo? Acha que é filho do Elon Musk?"
    ],
    "gasto_comida": [
        "🍔 iFood de novo? Sua panela serve de enfeite?",
        "🍕 Vai virar uma bola de tanto comer besteira!",
        "🍟 Dinheiro indo pro ralo e colesterol subindo. Parabéns!",
    ],
    "gasto_transporte": [
        "🚗 Uber? Acha que é rico pra ter motorista?",
        "🚌 Vai a pé que emagrece e economiza!",
    ],
    "parcelado": [
        "💳 Parcelou? O futuro você que se lasque pra pagar!",
        "💳 Mais uma dívida de estimação pra alimentar.",
        "💳 12x? Vai pagar isso até a Copa do Mundo!"
    ],
    "ganho": [
        "💰 Aleluia! Caiu um trocado na conta!",
        "💰 Não gasta tudo em cerveja, hein?",
        "💰 O milagre aconteceu: dinheiro na conta!"
    ]
}

# ================= SERVIDOR WEB =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"BOT V4 ZOEIRO ONLINE")
    try: HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except: pass
threading.Thread(target=start_web_server, daemon=True).start()

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {"ganho": ["Salário", "Extra", "Investimento"], "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "Mercado", "Saúde"]}, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "VR/VA", "Inter"],
        "goals": [],
        "config": {"zoeiro_mode": False} # Começa desligado
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_PARCELAS, REG_CAT, REG_DESC) = range(6)

def get_roast(tipo, categoria=""):
    if not db["config"]["zoeiro_mode"]:
        return "✅ Registrado com sucesso!"
    
    if tipo == "ganho": return random.choice(ROASTS["ganho"])
    if categoria in ["Alimentação", "Mercado"]: return random.choice(ROASTS["gasto_comida"])
    if categoria in ["Transporte"]: return random.choice(ROASTS["gasto_transporte"])
    return random.choice(ROASTS["gasto_generico"])

def get_main_menu():
    mode_icon = "🤡" if db["config"]["zoeiro_mode"] else "🤖"
    mode_text = "Modo Zoeiro: ON" if db["config"]["zoeiro_mode"] else "Modo Zoeiro: OFF"
    
    kb = [
        [InlineKeyboardButton("📝 Registrar Novo", callback_data="start_reg")],
        [InlineKeyboardButton("🆚 Mês x Mês", callback_data="compare_months"), InlineKeyboardButton(f"{mode_text}", callback_data="toggle_mode")],
        [InlineKeyboardButton("📊 Gráficos", callback_data="chart_pie"), InlineKeyboardButton("📄 Extrato CSV", callback_data="export_csv")],
        [InlineKeyboardButton("🗑️ Excluir", callback_data="menu_delete")]
    ]
    return InlineKeyboardMarkup(kb)

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = get_main_menu()
    text = "🤖 **FINANCEIRO V4**\n\nAgora com Parcelamento e Múltiplas Carteiras!\nEscolha:"
    if update.callback_query:
        await update.callback_query.answer()
        try: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except: await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

async def toggle_mode(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db)
    msg = "🤡 **MODO ZOEIRO ATIVADO!** Prepare-se para ser humilhado." if db["config"]["zoeiro_mode"] else "🤖 **Modo Sério Ativado.** Que tédio..."
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- FLUXO DE REGISTRO COMPLETO ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")], [InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]]
    await query.edit_message_text("**Passo 1: O que é?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Qual o valor total?**\nEx: `1200`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return REG_VALUE

async def reg_value(update, context):
    try:
        val = float(update.message.text.replace(',', '.'))
        context.user_data["temp_value"] = val
        
        # Seleção de Carteira
        kb = []
        for w in db["wallets"]: kb.append([InlineKeyboardButton(w, callback_data=f"wallet_{w}")])
        await update.message.reply_text("🏦 **Saiu de qual conta?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_WALLET
    except: await update.message.reply_text("❌ Valor inválido."); return REG_VALUE

async def reg_wallet(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_wallet"] = query.data.replace("wallet_", "")
    
    # Pergunta de Parcelamento (Só se for Gasto)
    if context.user_data["temp_type"] == "gasto":
        kb = [
            [InlineKeyboardButton("1x (À Vista)", callback_data="parc_1")],
            [InlineKeyboardButton("2x", callback_data="parc_2"), InlineKeyboardButton("3x", callback_data="parc_3")],
            [InlineKeyboardButton("6x", callback_data="parc_6"), InlineKeyboardButton("10x", callback_data="parc_10")],
            [InlineKeyboardButton("12x", callback_data="parc_12")]
        ]
        await query.edit_message_text("💳 **É parcelado?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_PARCELAS
    else:
        context.user_data["temp_parc"] = 1
        return await ask_category(query, context)

async def reg_parcelas(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_parc"] = int(query.data.replace("parc_", ""))
    return await ask_category(query, context)

async def ask_category(query, context):
    tipo = context.user_data["temp_type"]
    cats = db["categories"].get(tipo, [])
    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]] for i in range(0, len(cats), 2)]
    await query.edit_message_text("**Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_CAT

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    await query.edit_message_text("**Descrição:** (Digite ou pule)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Pular", callback_data="desc_Sem Descrição")]]), parse_mode="Markdown")
    return REG_DESC

async def reg_finish(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    
    # Lógica de Parcelamento
    parcelas = context.user_data["temp_parc"]
    valor_total = context.user_data["temp_value"]
    valor_parcela = valor_total / parcelas
    data_base = datetime.now()
    
    msg_final = ""
    
    for i in range(parcelas):
        # Calcula mês correto
        mes_venc = data_base + timedelta(days=30*i)
        data_str = mes_venc.strftime("%d/%m/%Y %H:%M")
        
        desc_final = desc
        if parcelas > 1:
            desc_final = f"{desc} ({i+1}/{parcelas})"
        
        item = {
            "id": str(uuid.uuid4())[:8],
            "type": context.user_data["temp_type"],
            "value": valor_parcela,
            "category": context.user_data["temp_cat"],
            "wallet": context.user_data["temp_wallet"],
            "description": desc_final,
            "date": data_str
        }
        db["transactions"].append(item)
    
    save_db(db)
    
    # Feedback
    roast = get_roast(context.user_data["temp_type"], context.user_data["temp_cat"])
    if parcelas > 1: roast = random.choice(ROASTS["parcelado"]) if db["config"]["zoeiro_mode"] else "✅ Parcelamento registrado!"
    
    msg = f"{roast}\n\n📝 **{desc}**\n💰 R$ {valor_total:.2f} ({parcelas}x de {valor_parcela:.2f})\n🏦 {context.user_data['temp_wallet']}"
    
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    
    return ConversationHandler.END

# --- COMPARATIVO MENSAL ---
async def compare_months(update, context):
    query = update.callback_query; await query.answer()
    
    # Pega mês atual e anterior
    hoje = datetime.now()
    mes_atual = hoje.strftime("%m/%Y")
    mes_anterior = (hoje.replace(day=1) - timedelta(days=1)).strftime("%m/%Y")
    
    gasto_atual = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_atual in t['date'])
    gasto_ant = sum(t['value'] for t in db["transactions"] if t['type'] == 'gasto' and mes_anterior in t['date'])
    
    diff = gasto_atual - gasto_ant
    icon = "📈" if diff > 0 else "📉"
    
    msg = f"🆚 **Batalha de Meses**\n\n"
    msg += f"📅 **{mes_anterior}:** R$ {gasto_ant:.2f}\n"
    msg += f"📅 **{mes_atual}:** R$ {gasto_atual:.2f}\n\n"
    msg += f"Diferença: {icon} R$ {diff:.2f}\n"
    
    if db["config"]["zoeiro_mode"]:
        if diff > 0: msg += "\n🤡 **Parabéns, você está gastando mais! Sua falência está próxima.**"
        else: msg += "\n🤡 **Economizou? Milagre!**"
        
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- UTILS (Chart, CSV, Delete, Cancel) ---
async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    gastos = {}
    for t in db["transactions"]:
        if t["type"] == "gasto": gastos[t["category"]] = gastos.get(t["category"], 0) + t["value"]
    if not gastos: return await query.edit_message_text("📭 Sem dados.", reply_markup=get_main_menu())
    plt.figure(figsize=(6, 6)); plt.pie(gastos.values(), labels=gastos.keys(), autopct='%1.1f%%'); plt.title("Gastos")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(photo=buf, caption="📊 Gastos", reply_markup=get_main_menu())

async def export_csv(update, context):
    query = update.callback_query; await query.answer()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Data", "Tipo", "Categoria", "Valor", "Carteira", "Descricao"])
    for t in db["transactions"]: writer.writerow([t["date"], t["type"], t["category"], t["value"], t.get("wallet", "-"), t["description"]])
    output.seek(0); b = io.BytesIO(output.getvalue().encode('utf-8')); b.name = "financas.csv"
    await query.message.reply_document(document=b, caption="📂 CSV", reply_markup=get_main_menu())

async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    kb = []
    for t in reversed(db["transactions"][-5:]): kb.append([InlineKeyboardButton(f"❌ {t['value']} - {t['description']}", callback_data=f"kill_{t['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Apagar Recentes:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db)
    await query.edit_message_text("✅ Apagado!", reply_markup=get_main_menu())

async def cancel(update, context):
    await start(update, context); return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv_reg = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type)], 
            REG_VALUE: [MessageHandler(filters.TEXT, reg_value)],
            REG_WALLET: [CallbackQueryHandler(reg_wallet)],
            REG_PARCELAS: [CallbackQueryHandler(reg_parcelas)],
            REG_CAT: [CallbackQueryHandler(reg_cat)], 
            REG_DESC: [CallbackQueryHandler(reg_finish), MessageHandler(filters.TEXT, reg_finish)]
        }, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_reg)
    
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(compare_months, pattern="^compare_months$"))
    app.add_handler(CallbackQueryHandler(chart_pie, pattern="^chart_pie$"))
    app.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    
    print("🤡 BOT V4 ZOEIRO RODANDO...")
    app.run_polling()
