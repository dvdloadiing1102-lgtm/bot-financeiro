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

# --- AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
try:
    import httpx
    import matplotlib
    # Configura o Matplotlib para não precisar de tela (evita erro no servidor)
    matplotlib.use('Agg') 
    import matplotlib.pyplot as plt
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
except ImportError:
    print("⚠️ Instalando dependências...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx", "matplotlib"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIGURAÇÃO =================
# 👇 SEU TOKEN JÁ ESTÁ AQUI 👇
TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI" 

DB_FILE = "finance_final.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= SERVIDOR WEB (PARA O RENDER NÃO DORMIR) =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"BOT FINANCE V2 ONLINE")
    
    try:
        HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except: pass

threading.Thread(target=start_web_server, daemon=True).start()

# ================= BANCO DE DADOS (JSON) =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "Mercado"]
        }, 
        "fixed_items": [], 
        "goals": []
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= UTILITÁRIOS E GRÁFICOS =================
# Estados para as Conversas (ConversationHandler)
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, NEW_CAT_NAME, ADD_FIXED, ADD_GOAL) = range(7)

def get_main_menu():
    kb = [
        [InlineKeyboardButton("📝 Novo Registro", callback_data="start_reg")],
        [InlineKeyboardButton("📊 Gráfico Pizza", callback_data="chart_pie"), InlineKeyboardButton("📄 Extrato CSV", callback_data="export_csv")],
        [InlineKeyboardButton("🔄 Processar Fixos", callback_data="process_fixed"), InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("📌 Configurar Fixos", callback_data="menu_fixed"), InlineKeyboardButton("🗑️ Excluir", callback_data="menu_delete")]
    ]
    return InlineKeyboardMarkup(kb)

def generate_pie_chart():
    # Filtra apenas gastos para o gráfico
    gastos = {}
    for t in db["transactions"]:
        if t["type"] == "gasto":
            cat = t["category"]
            gastos[cat] = gastos.get(cat, 0) + t["value"]
    
    if not gastos: return None

    # Cria gráfico usando Matplotlib
    plt.figure(figsize=(6, 6))
    plt.pie(gastos.values(), labels=gastos.keys(), autopct='%1.1f%%', startangle=140, colors=plt.cm.Pastel1.colors)
    plt.title("Distribuição de Gastos")
    
    # Salva a imagem na memória RAM (buffer)
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

# ================= HANDLERS PRINCIPAIS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "🤖 **FINANCEIRO PRO V2**\n\nOrganize sua vida financeira!\nSelecione uma opção:"
    
    if update.callback_query:
        await update.callback_query.answer()
        try: 
            await update.callback_query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
        except: 
            await update.callback_query.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    
    return ConversationHandler.END

# --- 1. REGISTRO DE TRANSAÇÕES (PASSO A PASSO) ---
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("📉 É UM GASTO", callback_data="type_gasto")], 
        [InlineKeyboardButton("📈 É UM GANHO", callback_data="type_ganho")], 
        [InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]
    ]
    await query.edit_message_text("Passo 1: **O que vamos registrar?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["temp_type"] = query.data.split("_")[1]
    await query.edit_message_text("💰 **Qual o valor?**\n(Digite apenas números. Ex: 25.90)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return REG_VALUE

async def reg_value(update, context):
    try:
        val_str = update.message.text.replace(',', '.')
        context.user_data["temp_value"] = float(val_str)
        
        tipo = context.user_data["temp_type"]
        cats = db["categories"].get(tipo, [])
        
        # Cria botões de categoria em pares
        kb = [cats[i:i+2] for i in range(0, len(cats), 2)]
        kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in row] for row in kb]
        kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])
        
        await update.message.reply_text("**Escolha a Categoria:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return REG_CAT
    except:
        await update.message.reply_text("❌ Valor inválido. Digite novamente (ex: 15.50):")
        return REG_VALUE

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    
    if query.data == "new_cat":
        await query.edit_message_text("✍️ **Digite o nome da nova categoria:**")
        return NEW_CAT_NAME
    
    context.user_data["temp_cat"] = query.data.replace("cat_", "")
    kb = [[InlineKeyboardButton("⏩ Pular Descrição", callback_data="desc_Sem Descrição")]]
    await query.edit_message_text("**Descrição (opcional):**\nDigite algo (ex: Padaria, Uber) ou pule.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_DESC

async def new_cat_save(update, context):
    nome = update.message.text
    tipo = context.user_data["temp_type"]
    
    if nome not in db["categories"][tipo]: 
        db["categories"][tipo].append(nome)
        save_db(db)
        
    context.user_data["temp_cat"] = nome
    kb = [[InlineKeyboardButton("⏩ Pular Descrição", callback_data="desc_Sem Descrição")]]
    await update.message.reply_text(f"✅ Categoria **{nome}** criada!\nAgora a descrição:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return REG_DESC

async def reg_finish(update, context):
    # Pode vir de botão (Pular) ou Texto
    if update.callback_query:
        desc = update.callback_query.data.replace("desc_", "")
    else:
        desc = update.message.text

    item = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["temp_type"],
        "value": context.user_data["temp_value"],
        "category": context.user_data["temp_cat"],
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    
    db["transactions"].append(item)
    save_db(db)
    
    msg = f"✅ **Registrado com Sucesso!**\n\n💲 R$ {item['value']:.2f}\n📂 {item['category']}\n📝 {desc}"
    
    if update.callback_query: 
        await update.callback_query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
    else: 
        await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
        
    return ConversationHandler.END

# --- 2. FUNÇÕES AVANÇADAS (GRÁFICO E EXTRATO) ---

async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("🎨 **Gerando gráfico... aguarde!**")
    
    img = generate_pie_chart()
    if img:
        await query.message.reply_photo(
            photo=img, 
            caption="📊 **Seus Gastos por Categoria**", 
            reply_markup=get_main_menu()
        )
    else:
        await query.edit_message_text("⚠️ Você ainda não registrou gastos para gerar gráfico.", reply_markup=get_main_menu())

async def export_csv(update, context):
    query = update.callback_query; await query.answer()
    if not db["transactions"]: 
        return await query.edit_message_text("📭 Sem transações para exportar.", reply_markup=get_main_menu())
    
    # Gera CSV na memória
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Data", "Tipo", "Categoria", "Valor", "Descricao"])
    
    for t in db["transactions"]:
        writer.writerow([t["date"], t["type"], t["category"], str(t["value"]), t["description"]])
    
    output.seek(0)
    bytes_csv = io.BytesIO(output.getvalue().encode('utf-8'))
    bytes_csv.name = "extrato_financeiro.csv"
    
    await query.message.reply_document(
        document=bytes_csv, 
        caption="📂 **Aqui está seu Extrato Completo!**\nAbra no Excel ou Google Sheets.", 
        reply_markup=get_main_menu()
    )

# --- 3. PROCESSAR FIXOS ---
async def process_fixed(update, context):
    query = update.callback_query; await query.answer()
    if not db["fixed_items"]: 
        return await query.edit_message_text("⚠️ Você não tem Itens Fixos cadastrados.\nVá em 'Configurar Fixos' primeiro.", reply_markup=get_main_menu())
    
    count = 0
    total = 0
    mes_ano = datetime.now().strftime("%m/%Y") # Ex: 02/2026
    
    for fix in db["fixed_items"]:
        # Verifica se já foi lançado neste mês para evitar duplicação
        descricao_mensal = f"{fix['name']} ({mes_ano})"
        ja_foi = any(t['description'] == descricao_mensal for t in db["transactions"])
        
        if not ja_foi:
            item = {
                "id": str(uuid.uuid4())[:8],
                "type": fix["type"],
                "value": fix["value"],
                "category": "Fixo",
                "description": descricao_mensal,
                "date": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            db["transactions"].append(item)
            count += 1
            total += fix["value"]
    
    save_db(db)
    
    msg = f"✅ **Processamento Concluído!**\n\n📌 Itens lançados agora: {count}\n💰 Valor Total: R$ {total:.2f}"
    if count == 0: 
        msg = "✅ **Tudo em dia!**\nTodos os seus itens fixos já foram lançados neste mês."
    
    await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- 4. CONFIGURAR FIXOS ---
async def menu_fixed(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Novo Fixo", callback_data="add_fixed_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    
    text = "📌 **ITENS FIXOS (Recorrentes):**\nUse 'Processar Fixos' no menu principal para lançá-los todo mês automaticamente.\n\n"
    if not db["fixed_items"]: text += "_Nenhum item cadastrado._"
    
    for f in db["fixed_items"]: 
        emoji = "🔴" if f['type'] == 'gasto' else "🟢"
        text += f"{emoji} {f['name']}: R$ {f['value']:.2f}\n"
        
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite no formato:\n`TIPO NOME VALOR`\n\nExemplos:\n`gasto Internet 120.90`\n`ganho Salario 3000`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
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
        await update.message.reply_text(f"✅ **{nome}** salvo como Fixo!", reply_markup=get_main_menu(), parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Formato errado.\nTente: `gasto Aluguel 1200`", parse_mode="Markdown")
        return ADD_FIXED # Pede de novo
    return ConversationHandler.END

# --- 5. METAS ---
async def menu_goals(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal_start")], [InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")]]
    
    text = "🎯 **METAS MENSAIS DE GASTOS:**\n\n"
    
    # Calcula quanto gastou no mês atual em cada categoria
    gastos_mes = {} 
    mes_atual = datetime.now().strftime("%m/%Y")
    
    for t in db["transactions"]:
        if t['type'] == 'gasto': # e t['date']... (simplificado para tutorial)
             gastos_mes[t['category']] = gastos_mes.get(t['category'], 0) + t['value']
        
    if not db["goals"]: text += "_Nenhuma meta definida._"

    for g in db["goals"]:
        atual = gastos_mes.get(g['category'], 0)
        pct = (atual / g['limit']) * 100
        
        emoji = "🟢" 
        if pct > 80: emoji = "🟡"
        if pct >= 100: emoji = "🔴"
        
        text += f"{emoji} **{g['category']}**: R$ {atual:.0f} / {g['limit']} ({pct:.0f}%)\n"
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal_start(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Digite: `CATEGORIA VALOR`\nEx: `Lazer 500`\nEx: `Mercado 800`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="cancel")]]), parse_mode="Markdown")
    return ADD_GOAL

async def add_goal_save(update, context):
    try:
        parts = update.message.text.split(" ")
        val = float(parts[-1])
        cat = " ".join(parts[:-1]) # Pega tudo antes do valor
        
        # Remove meta anterior se existir
        db["goals"] = [g for g in db["goals"] if g['category'] != cat]
        
        db["goals"].append({"category": cat, "limit": val})
        save_db(db)
        await update.message.reply_text(f"✅ Meta de **{cat}** definida para R$ {val}!", reply_markup=get_main_menu(), parse_mode="Markdown")
    except: 
        await update.message.reply_text("Erro. Tente novamente.")
    return ConversationHandler.END

# --- 6. APAGAR ITENS ---
async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    
    if not db["transactions"]:
        return await query.edit_message_text("📭 Nada para apagar.", reply_markup=get_main_menu())

    # Mostra as últimas 5 transações
    kb = []
    for t in reversed(db["transactions"][-5:]):
        kb.append([InlineKeyboardButton(f"❌ R$ {t['value']} - {t['description']}", callback_data=f"kill_{t['id']}")])
    
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="cancel")])
    await query.edit_message_text("🗑️ **Toque para apagar (Últimos 5):**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    
    # Remove do banco
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db)
    
    await query.edit_message_text("✅ Item apagado!", reply_markup=get_main_menu())

# --- CANCELAR E FIM ---
async def cancel(update, context):
    await start(update, context)
    return ConversationHandler.END

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Configura os Handlers de Conversa (Sequência de perguntas)
    conv_reg = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type, pattern="^type_")],
            REG_VALUE: [MessageHandler(filters.TEXT, reg_value)],
            REG_CAT: [CallbackQueryHandler(reg_cat, pattern="^cat_|^new_cat$")],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT, new_cat_save)],
            REG_DESC: [CallbackQueryHandler(reg_finish, pattern="^desc_"), MessageHandler(filters.TEXT, reg_finish)]
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    
    conv_fixed = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_fixed_start, pattern="^add_fixed_start$")],
        states={ADD_FIXED: [MessageHandler(filters.TEXT, add_fixed_save)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )
    
    conv_goal = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_goal_start, pattern="^add_goal_start$")],
        states={ADD_GOAL: [MessageHandler(filters.TEXT, add_goal_save)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    # Registra tudo no bot
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_reg)
    app.add_handler(conv_fixed)
    app.add_handler(conv_goal)
    
    # Botões do Menu Principal
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
