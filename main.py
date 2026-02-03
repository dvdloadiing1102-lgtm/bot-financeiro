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

# ⚠️ GERE UM TOKEN NOVO NO BOTFATHER E COLOQUE NAS VARIÁVEIS DO RENDER!
# Se for rodar local, troque abaixo, mas não suba pro GitHub com a senha.
TOKEN = os.getenv("BOT_TOKEN", "SEU_NOVO_TOKEN_AQUI") 
RENDER_URL = "https://bot-financeiro-hu1p.onrender.com"
DB_FILE = "finance_master.json"

# ================= KEEP ALIVE SERVER (CORREÇÃO ERRO 501) =================

def start_web_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"BOT ONLINE")
        
        # ADICIONADO: Necessário para o UptimeRobot/Render não dar erro 501
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

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
    if not os.path.exists(DB_FILE):
        return default
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return default

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

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
        [InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat_menu")] # Alterado ID para evitar conflito
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="start")]])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    msg = "🤖 **FINANCEIRO PRO — ONLINE**\nEscolha:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= REGISTRO =================

async def start_register(update, context):
    q = update.callback_query
    await q.answer()

    # CORREÇÃO: Pega o tipo corretamente
    context.user_data["type"] = q.data.replace("new_", "")
    context.user_data["step"] = "value"

    await q.edit_message_text(f"Digite o valor do **{context.user_data['type'].upper()}**:", reply_markup=back_btn(), parse_mode="Markdown")

async def receive_text(update, context):
    step = context.user_data.get("step")
    text = update.message.text.strip()

    # VALOR
    if step == "value":
        try:
            val = float(text.replace(",", "."))
            context.user_data["value"] = val
            context.user_data["step"] = "category"

            tipo = context.user_data["type"]
            # Proteção caso o tipo não exista
            cats = db["categories"].get(tipo, ["Geral"])

            kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
            kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat_flow")]) # ID diferente para fluxo
            kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="start")])

            await update.message.reply_text("Escolha a categoria:", reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 25.90)")
        return

    # DESCRIÇÃO (FINALIZAR)
    if step == "desc":
        save_transaction(context, text)
        await update.message.reply_text("✅ Registrado com sucesso!", reply_markup=main_menu())
        context.user_data.clear()
        return

    # NOVA CATEGORIA (SALVAR)
    if step == "new_cat_name":
        # Se veio do menu principal, assume gasto como padrão se não tiver tipo
        tipo = context.user_data.get("type", "gasto")
        
        if text not in db["categories"][tipo]:
            db["categories"][tipo].append(text)
            save_db(db)

        # Se estava no meio de um registro (tem valor), continua o fluxo
        if "value" in context.user_data:
            context.user_data["category"] = text
            context.user_data["step"] = "desc"
            await update.message.reply_text(f"Categoria **{text}** criada e selecionada!\nAgora digite a descrição:", parse_mode="Markdown")
        else:
            # Se veio do menu principal, apenas confirma e sai
            await update.message.reply_text(f"Categoria **{text}** criada em {tipo}!", reply_markup=main_menu(), parse_mode="Markdown")
            context.user_data.clear()
        return

    # FIXOS
    if step == "fixed_add":
        try:
            name, val = text.rsplit(" ", 1)
            val = float(val.replace(",", "."))
            db["fixed"].append({"name": name, "value": val})
            save_db(db)
            await update.message.reply_text("✅ Fixo salvo!", reply_markup=main_menu())
        except:
            await update.message.reply_text("❌ Erro. Use formato: `Netflix 39.90`", parse_mode="Markdown")
        context.user_data.clear()
        return

    # META
    if step == "goal_add":
        try:
            cat, val = text.rsplit(" ", 1)
            val = float(val.replace(",", "."))
            db["goals"].append({"category": cat, "limit": val})
            save_db(db)
            await update.message.reply_text("🎯 Meta salva!", reply_markup=main_menu())
        except:
            await update.message.reply_text("❌ Erro. Use formato: `iFood 300`", parse_mode="Markdown")
        context.user_data.clear()
        return

# ================= CATEGORIA E MENUS EXTRAS =================

async def choose_category(update, context):
    q = update.callback_query
    await q.answer()

    context.user_data["category"] = q.data.replace("cat_", "")
    context.user_data["step"] = "desc"

    await q.edit_message_text(f"Categoria: **{context.user_data['category']}**\nDigite a descrição:", reply_markup=back_btn(), parse_mode="Markdown")

async def start_new_category(update, context):
    q = update.callback_query
    await q.answer()
    
    # Verifica se veio do menu principal
    if q.data == "new_cat_menu":
        context.user_data["type"] = "gasto" # Padrão
        
    context.user_data["step"] = "new_cat_name"
    await q.edit_message_text("Digite o nome da nova categoria:", reply_markup=back_btn())

# FALTAVAM ESTAS FUNÇÕES NO SEU CÓDIGO ANTERIOR
async def menu_fixed(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "fixed_add"
    
    txt = "**LISTA DE FIXOS:**\n"
    for f in db["fixed"]: txt += f"- {f['name']}: R$ {f['value']:.2f}\n"
    
    await q.edit_message_text(f"{txt}\nDigite para adicionar: `Nome Valor`", reply_markup=back_btn(), parse_mode="Markdown")

async def menu_goals(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "goal_add"
    
    txt = "**SUAS METAS:**\n"
    for g in db["goals"]: txt += f"- {g['category']}: R$ {g['limit']:.2f}\n"
    
    await q.edit_message_text(f"{txt}\nDigite para adicionar: `Categoria Valor`", reply_markup=back_btn(), parse_mode="Markdown")

async def trash(update, context):
    q = update.callback_query
    await q.answer()
    db["transactions"] = []
    save_db(db)
    await q.edit_message_text("🗑️ Lixeira esvaziada.", reply_markup=main_menu())

# ================= SAVE =================

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

# ================= RELATÓRIO =================

async def report(update, context):
    q = update.callback_query
    await q.answer()

    gasto = sum(t["value"] for t in db["transactions"] if t["type"] == "gasto")
    ganho = sum(t["value"] for t in db["transactions"] if t["type"] == "ganho")
    saldo = ganho - gasto

    msg = (
        f"📊 **RELATÓRIO GERAL**\n\n"
        f"💰 Ganhos: R$ {ganho:.2f}\n"
        f"💸 Gastos: R$ {gasto:.2f}\n"
        f"📉 **Saldo: R$ {saldo:.2f}**\n\n"
    )

    if saldo < 0:
        msg += "⚠️ Você está no vermelho!"

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= HISTÓRICO =================

async def history(update, context):
    q = update.callback_query
    await q.answer()

    if not db["transactions"]:
        await q.edit_message_text("📭 Sem registros ainda.", reply_markup=main_menu())
        return

    msg = "📋 **ÚLTIMOS LANÇAMENTOS**\n\n"
    for t in reversed(db["transactions"][-15:]):
        icon = "🔴" if t["type"] == "gasto" else "🟢"
        msg += f"{icon} {t['category']} • R$ {t['value']:.2f}\n_{t['description']} ({t['date']})_\n\n"

    # Corta mensagem se for muito longa
    if len(msg) > 4000: msg = msg[:4000] + "..."
    
    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= MAIN =================

async def main():
    if not TOKEN:
        print("Erro: Token não configurado.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # CORREÇÃO DE CONFLITO: Regex específico para gasto/ganho
    app.add_handler(CallbackQueryHandler(start_register, pattern="^new_(gasto|ganho)$"))
    
    # Handler para categorias (menu e fluxo)
    app.add_handler(CallbackQueryHandler(start_new_category, pattern="^new_cat"))
    
    # Seleção de categoria existente
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))

    # Menus Extras
    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(history, pattern="^history$"))
    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(trash, pattern="^trash$"))

    # Voltar / Start via botão
    app.add_handler(CallbackQueryHandler(start, pattern="^start$"))
    
    # Texto (sempre o último)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    # Inicia o ping em background
    asyncio.create_task(keep_alive())

    print("🤖 BOT ONLINE — OK")
    
    # Configuração correta para Render (sem conflito de loop)
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass