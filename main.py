import os
import json
import uuid
import asyncio
import httpx
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ================= CONFIG =================

# Tente pegar do ambiente, ou use a string direta (Cuidado com segurança!)
TOKEN = os.getenv("BOT_TOKEN", "SEU_TOKEN_AQUI") 
RENDER_URL = "https://bot-financeiro-hu1p.onrender.com"
DB_FILE = "finance_master.json"

# ================= KEEP ALIVE SERVER =================

def start_web_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"BOT ONLINE")

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=start_web_server, daemon=True).start()

# ================= PING RENDER =================

async def keep_alive():
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await asyncio.sleep(600) # 10 minutos
                await client.get(RENDER_URL, timeout=10)
            except:
                pass

# ================= DATABASE =================

def load_db():
    default = {
        "transactions": [],
        "categories": {
            "gasto": ["Alimentação", "Transporte", "Casa", "Lazer", "iFood"],
            "ganho": ["Salário", "Extra"]
        },
        "fixed": [],
        "goals": []
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= MENUS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Novo Gasto", callback_data="new_gasto"),
         InlineKeyboardButton("💰 Novo Ganho", callback_data="new_ganho")],
        [InlineKeyboardButton("📦 Fixos", callback_data="menu_fixed"),
         InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report"),
         InlineKeyboardButton("📋 Histórico", callback_data="history")],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data="trash")],
        [InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat_menu")]
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="start")]])

# ================= START (CORRIGIDO) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    msg = "🤖 **FINANCEIRO PRO — ONLINE**\nEscolha uma opção:"
    
    # Verifica se veio de um comando (/start) ou de um botão (Voltar)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= REGISTRO DE TRANSAÇÃO =================

async def start_register(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["type"] = q.data.replace("new_", "")
    context.user_data["step"] = "value"
    await q.edit_message_text("Digite o valor (ex: 25.50):", reply_markup=back_btn())

# ================= NOVA CATEGORIA (CORRIGIDO) =================

async def start_new_category(update, context):
    q = update.callback_query
    await q.answer()
    # Define se veio do menu (cria categoria genérica) ou fluxo
    context.user_data["step"] = "new_cat_name"
    # Se veio do menu principal, assume que é para Gasto por padrão
    if "type" not in context.user_data:
        context.user_data["type"] = "gasto" 
        
    await q.edit_message_text(f"Digite o nome da nova categoria de {context.user_data['type']}:", reply_markup=back_btn())

# ================= FIXOS E METAS (FALTAVA) =================

async def menu_fixed(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "fixed_add"
    
    txt = "📋 **SEUS FIXOS:**\n"
    for f in db["fixed"]:
        txt += f"- {f['name']}: R$ {f['value']}\n"
        
    await q.edit_message_text(f"{txt}\nPara adicionar, digite: `Nome Valor`\nEx: Netflix 55.90", reply_markup=back_btn(), parse_mode="Markdown")

async def menu_goals(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "goal_add"
    
    txt = "🎯 **SUAS METAS:**\n"
    for g in db["goals"]:
        txt += f"- {g['category']}: Limite R$ {g['limit']}\n"

    await q.edit_message_text(f"{txt}\nPara adicionar, digite: `Categoria Valor`\nEx: Lazer 200", reply_markup=back_btn(), parse_mode="Markdown")

# ================= PROCESSADOR DE TEXTO =================

async def receive_text(update, context):
    step = context.user_data.get("step")
    text = update.message.text.strip()

    # 1. RECEBER VALOR
    if step == "value":
        try:
            val = float(text.replace(",", "."))
            context.user_data["value"] = val
            context.user_data["step"] = "category"

            tipo = context.user_data["type"]
            cats = db["categories"].get(tipo, []) # .get evita crash se tipo não existir

            kb = []
            for c in cats:
                kb.append([InlineKeyboardButton(c, callback_data=f"cat_{c}")])
            
            kb.append([InlineKeyboardButton("➕ Criar Categoria", callback_data="new_cat_flow")])
            kb.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="start")])

            await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return

    # 2. RECEBER DESCRIÇÃO
    if step == "desc":
        save_transaction(context, text)
        await update.message.reply_text("✅ Transação Registrada!", reply_markup=main_menu())
        context.user_data.clear()
        return

    # 3. CRIAR NOVA CATEGORIA
    if step == "new_cat_name":
        tipo = context.user_data.get("type", "gasto")
        if text not in db["categories"][tipo]:
            db["categories"][tipo].append(text)
            save_db(db)
        
        # Se estava no meio de um fluxo de transação, volta pra escolher categoria
        if "value" in context.user_data:
             context.user_data["step"] = "category"
             await update.message.reply_text(f"Categoria '{text}' criada! Agora escolha ela na lista (clique em Voltar se não aparecer).", reply_markup=back_btn())
        else:
             # Se veio do menu principal, encerra
             await update.message.reply_text(f"Categoria '{text}' criada com sucesso!", reply_markup=main_menu())
             context.user_data.clear()
        return

    # 4. ADICIONAR FIXO
    if step == "fixed_add":
        try:
            name, val = text.rsplit(" ", 1)
            val = float(val.replace(",", "."))
            db["fixed"].append({"name": name, "value": val})
            save_db(db)
            await update.message.reply_text("✅ Custo Fixo salvo!", reply_markup=main_menu())
        except:
            await update.message.reply_text("❌ Erro. Use o formato: `Aluguel 1200`", parse_mode="Markdown")
        context.user_data.clear()
        return

    # 5. ADICIONAR META
    if step == "goal_add":
        try:
            cat, val = text.rsplit(" ", 1)
            val = float(val.replace(",", "."))
            db["goals"].append({"category": cat, "limit": val})
            save_db(db)
            await update.message.reply_text("🎯 Meta definida!", reply_markup=main_menu())
        except:
            await update.message.reply_text("❌ Erro. Use o formato: `Lazer 500`", parse_mode="Markdown")
        context.user_data.clear()
        return

# ================= CALLBACKS AUXILIARES =================

async def choose_category(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["category"] = q.data.replace("cat_", "")
    context.user_data["step"] = "desc"
    await q.edit_message_text("📝 Digite uma descrição (ex: Mercado):", reply_markup=back_btn())

def save_transaction(context, desc):
    db["transactions"].append({
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["type"],
        "value": context.user_data["value"],
        "category": context.user_data["category"],
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_db(db)

# ================= RELATÓRIOS E LIXEIRA =================

async def report(update, context):
    q = update.callback_query
    await q.answer()
    
    gasto = sum(t["value"] for t in db["transactions"] if t["type"] == "gasto")
    ganho = sum(t["value"] for t in db["transactions"] if t["type"] == "ganho")
    saldo = ganho - gasto
    
    msg = (f"📊 **RELATÓRIO FINANCEIRO**\n\n"
           f"🟢 Entradas: R$ {ganho:.2f}\n"
           f"🔴 Saídas:   R$ {gasto:.2f}\n"
           f"──────────────\n"
           f"💰 **Saldo:   R$ {saldo:.2f}**")
           
    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

async def history(update, context):
    q = update.callback_query
    await q.answer()
    
    if not db["transactions"]:
        await q.edit_message_text("📭 Histórico vazio.", reply_markup=main_menu())
        return

    msg = "📋 **ÚLTIMOS 10 REGISTROS**\n\n"
    for t in reversed(db["transactions"][-10:]):
        icon = "🔴" if t["type"] == "gasto" else "🟢"
        msg += f"{icon} {t['category']} | R$ {t['value']:.2f}\n   _{t['description']}_\n\n"
        
    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

async def trash(update, context):
    q = update.callback_query
    await q.answer()
    # Limpa transações (simples)
    db["transactions"] = []
    save_db(db)
    await q.edit_message_text("🗑️ Todas as transações foram apagadas.", reply_markup=main_menu())

# ================= MAIN =================

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Comandos e Menu Principal
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^start$")) # Botão Voltar

    # Fluxo de Registro
    app.add_handler(CallbackQueryHandler(start_register, pattern="^new_(gasto|ganho)$"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    
    # Categorias (Fluxo e Menu)
    app.add_handler(CallbackQueryHandler(start_new_category, pattern="^new_cat")) 
    
    # Menus Secundários
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(history, pattern="^history$"))
    app.add_handler(CallbackQueryHandler(trash, pattern="^trash$"))

    # Handler de Texto Geral (Deve ser o último)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    # Mantém servidor vivo
    asyncio.create_task(keep_alive())

    print("🤖 BOT INICIADO COM SUCESSO!")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot parado pelo usuário.")