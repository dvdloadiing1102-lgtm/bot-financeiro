import os
import sys
import json
import logging
import uuid
import threading
import time
import io
import csv
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- AUTO-INSTALAÇÃO ---
try:
    import httpx
    import matplotlib
    matplotlib.use('Agg') # Backend não-interativo para servidor
    import matplotlib.pyplot as plt
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    print("⚠️ Instalando dependências...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx", "matplotlib"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
TOKEN = "SEU_TOKEN_AQUI" # ⚠️ COLOQUE SEU TOKEN AQUI
DB_FILE = "finance_final.json"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= SERVIDOR WEB (ANTI-CRASH) =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"BOT FINANCE V2 ONLINE")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
threading.Thread(target=start_web_server, daemon=True).start()

# ================= BANCO DE DADOS =================
def load_db():
    default = {"transactions": [], "categories": {"ganho": ["Salário", "Extra", "Investimento"], "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "Mercado"]}, "fixed_items": [], "goals": []}
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS E GRÁFICOS =================
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, NEW_CAT_NAME, ADD_FIXED, ADD_GOAL) = range(7)

def get_main_menu():
    kb = [
        [InlineKeyboardButton("📝 Novo Registro", callback_data="start_reg")],
        [InlineKeyboardButton("📊 Gráfico de Gastos", callback_data="chart_pie"), InlineKeyboardButton("📄 Extrato CSV", callback_data="export_csv")],
        [InlineKeyboardButton("🔄 Processar Fixos", callback_data="process_fixed"), InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("📌 Configurar Fixos", callback_data="menu_fixed"), InlineKeyboardButton("🗑️ Excluir", callback_data="menu_delete")]
    ]
    return InlineKeyboardMarkup(kb)

def generate_pie_chart():
    # Filtra gastos
    gastos = {}
    for t in db["transactions"]:
        if t["type"] == "gasto":
            cat = t["category"]
            gastos[cat] = gastos.get(cat, 0) + t["value"]
    
    if not gastos: return None

    # Cria gráfico
    plt.figure(figsize=(6, 6))
    plt.pie(gastos.values(), labels=gastos.keys(), autopct='%1.1f%%', startangle=140, colors=plt.cm.Pastel1.colors)
    plt.title("Distribuição de Gastos")
    
    # Salva em memória
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

# ================= HANDLERS PRINCIPAIS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "🤖 **FINANCEIRO PRO V2**\nSelecione uma opção:"
    if update.callback_query:
        await update.callback_query.answer()
        try: await update.callback_query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
        except: await update.callback_query.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

# --- REGISTRO DE TRANSAÇÕES ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📉 GASTO", callback_data="type_gasto"), InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")], [InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]]
    await query.edit_message_text("**O que vamos registrar?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Qual o valor?** (Ex: 25.90)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return REG_VALUE

async def reg_value(update, context):
    try:
        context.user_data["temp_value"] = float(update.message.text.replace(',', '.'))
        tipo = context.user_data["temp_type"]
        cats = db["categories"].get(tipo, [])
        kb = [cats[i:i+2] for i in range(0, len(cats), 2)]
        kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in row] for row in kb]
        kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])
        await update.message.reply_text("**Escolha a Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_CAT
    except:
        await update.message.reply_text("❌ Número inválido.")
        return REG_VALUE

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    if query.data == "new_cat":
        await query.edit_message_text("✍️ **Nome da nova categoria:**")
        return NEW_CAT_NAME
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    kb = [[InlineKeyboardButton("Pular Descrição", callback_data="desc_Sem Descrição")]]
    await query.edit_message_text("**Descrição (opcional):**\nDigite ou pule.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_DESC

async def new_cat_save(update, context):
    nome, tipo = update.message.text, context.user_data["temp_type"]
    if nome not in db["categories"][tipo]: db["categories"][tipo].append(nome); save_db(db)
    context.user_data["temp_cat"] = nome
    await update.message.reply_text("**Descrição (opcional):**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Pular", callback_data="desc_Sem Descrição")]]), parse_mode="Markdown")
    return REG_DESC

async def reg_finish(update, context):
    desc = update.callback_query.data.replace("desc_", "") if update.callback_query else update.message.text
    item = {"id": str(uuid.uuid4())[:8], "type": context.user_data["temp_type"], "value": context.user_data["temp_value"], "category": context.user_data["temp_cat"], "description": desc, "date": datetime.now().strftime("%d/%m/%Y %H:%M")}
    db["transactions"].append(item); save_db(db)
    msg = f"✅ **Registrado!**\nR$ {item['value']:.2f} ({item['category']})"
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

# --- FUNÇÕES V2.0 ---
async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("🎨 Gerando gráfico...")
    img = generate_pie_chart()
    if img:
        await query.message.reply_photo(photo=img, caption="📊 **Seus Gastos por Categoria**", reply_markup=get_main_menu())
    else:
        await query.edit_message_text("⚠️ Sem dados de gastos para gerar gráfico.", reply_markup=get_main_menu())

async def export_csv(update, context):
    query = update.callback_query; await query.answer()
    if not db["transactions"]: return await query.edit_message_text("📭 Sem transações.", reply_markup=get_main_menu())
    
    # Gera CSV na memória
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Data", "Tipo", "Categoria", "Valor", "Descricao"])
    for t in db["transactions"]:
        writer.writerow([t["date"], t["type"], t["category"], str(t["value"]), t["description"]])
    
    output.seek(0)
    bytes_csv = io.BytesIO(output.getvalue().encode('utf-8'))
    bytes_csv.name = "extrato_financeiro.csv"
    
    await query.message.reply_document(document=bytes_csv, caption="📂 **Seu Extrato Completo**", reply_markup=get_main_menu())

async def process_fixed(update, context):
    query = update.callback_query; await query.answer()
    if not db["fixed_items"]: return await query.edit_message_text("⚠️ Nenhum item fixo cadastrado.", reply_markup=get_main_menu())
    
    count = 0
    total = 0
    # Verifica duplicidade simples (mesmo mês/ano e mesma descrição)
    mes_ano = datetime.now().strftime("%m/%Y")
    
    for fix in db["fixed_items"]:
        # Checa se já rodou este item neste mês
        ja_foi = any(t['description'] == f"{fix['name']} ({mes_ano})" for t in db["transactions"])
        
        if not ja_foi:
            item = {
                "id": str(uuid.uuid4())[:8],
                "type": fix["type"],
                "value": fix["value"],
                "category": "Fixo",
                "description": f"{fix['name']} ({mes_ano})",
                "date": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            db["transactions"].append(item)
            count += 1
            total += fix["value"]
    
    save_db(db)
    msg = f"✅ **Processamento Concluído!**\n\n📌 Itens lançados: {count}\n💰 Valor Total: R$ {total:.2f}"
    if count == 0: msg = "✅ Todos os itens fixos já foram lançados neste mês!"
    
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- GERENCIAMENTO DE FIXOS ---
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Novo Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    text = "📌 **ITENS FIXOS (Recorrentes):**\nUse 'Processar Fixos' para lançá-los todo mês.\n\n"
    for f in db["fixed_items"]: text += f"- {f['name']} ({f['type']}): R$ {f['value']:.2f}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `TIPO NOME VALOR`\nEx: `gasto Aluguel 1200`\nEx: `ganho Salario 3000`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return ADD_FIXED

async def add_fixed_save(update, context):
    try:
        parts = update.message.text.split(" ")
        tipo = parts[0].lower()
        if tipo not in ["gasto", "ganho"]: raise ValueError
        val = float(parts[-1])
        nome = " ".join(parts[1:-1])
        db["fixed_items"].append({"type": tipo, "name": nome, "value": val})
        save_db(db)
        await update.message.reply_text("✅ Fixo Salvo!", reply_markup=get_main_menu())
    except:
        await update.message.reply_text("❌ Formato errado. Use: `gasto Internet 100`")
    return ConversationHandler.END

# --- OUTROS (Goals, Delete, Cancel) ---
async def menu_goals(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    text = "🎯 **METAS MENSAIS:**\n"
    # Calcula gasto atual vs meta
    gastos_mes = {} 
    for t in db["transactions"]:
        if t['type'] == 'gasto': gastos_mes[t['category']] = gastos_mes.get(t['category'], 0) + t['value']
        
    for g in db["goals"]:
        atual = gastos_mes.get(g['category'], 0)
        pct = (atual / g['limit']) * 100
        emoji = "🟢" if pct < 80 else "🟡" if pct < 100 else "🔴"
        text += f"{emoji} **{g['category']}**: R$ {atual:.0f} / {g['limit']} ({pct:.0f}%)\n"
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `CATEGORIA VALOR`\nEx: `Lazer 500`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return ADD_GOAL

async def add_goal_save(update, context):
    try:
        cat, val = update.message.text.rsplit(" ", 1)
        db["goals"].append({"category": cat, "limit": float(val)})
        save_db(db)
        await update.message.reply_text("✅ Meta definida!", reply_markup=get_main_menu())
    except: await update.message.reply_text("Erro. Tente novamente.")
    return ConversationHandler.END

async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    # Mostra últimas 5 para apagar
    kb = []
    for t in reversed(db["transactions"][-5:]):
        kb.append([InlineKeyboardButton(f"❌ R$ {t['value']} - {t['description']}", callback_data=f"kill_{t['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Toque para apagar:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db)
    await query.edit_message_text("✅ Apagado!", reply_markup=get_main_menu())

async def cancel(update, context):
    await start(update, context)
    return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers de Conversa
    conv_reg = ConversationHandler(entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")], states={REG_TYPE: [CallbackQueryHandler(reg_type)], REG_VALUE: [MessageHandler(filters.TEXT, reg_value)], REG_CAT: [CallbackQueryHandler(reg_cat)], NEW_CAT_NAME: [MessageHandler(filters.TEXT, new_cat_save)], REG_DESC: [CallbackQueryHandler(reg_finish), MessageHandler(filters.TEXT, reg_finish)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    conv_fixed = ConversationHandler(entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")], states={ADD_FIXED: [MessageHandler(filters.TEXT, add_fixed_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])
    conv_goal = ConversationHandler(entry_points=[CallbackQueryHandler(add_goal_start, pattern="^add_goal_start$")], states={ADD_GOAL: [MessageHandler(filters.TEXT, add_goal_save)]}, fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_reg); app.add_handler(conv_fixed); app.add_handler(conv_goal)
    
    # Handlers de Botão
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(chart_pie, pattern="^chart_pie$"))
    app.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$"))
    app.add_handler(CallbackQueryHandler(process_fixed, pattern="^process_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    
    print("🔥 BOT FINANCEIRO V2.0 RODANDO...")
    app.run_polling()
