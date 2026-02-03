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

TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI"
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
                await asyncio.sleep(600)
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
        [InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")]
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="start")]])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🤖 **FINANCEIRO PRO — ONLINE**\nEscolha:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

# ================= REGISTRO =================

async def start_register(update, context):
    q = update.callback_query
    await q.answer()

    context.user_data["type"] = q.data.replace("new_", "")
    context.user_data["step"] = "value"

    await q.edit_message_text("Digite o valor:", reply_markup=back_btn())

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
            cats = db["categories"][tipo]

            kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
            kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])
            kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="start")])

            await update.message.reply_text("Escolha a categoria:", reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text("❌ Valor inválido")
        return

    # DESCRIÇÃO
    if step == "desc":
        save_transaction(context, text)
        await update.message.reply_text("✅ Registrado!", reply_markup=main_menu())
        context.user_data.clear()
        return

    # NOVA CATEGORIA
    if step == "new_cat_name":
        tipo = context.user_data.get("type", "gasto")
        if text not in db["categories"][tipo]:
            db["categories"][tipo].append(text)
            save_db(db)

        context.user_data["category"] = text
        context.user_data["step"] = "desc"

        await update.message.reply_text("Categoria criada! Agora descrição:")
        return

    # FIXOS
    if step == "fixed_add":
        try:
            name, val = text.rsplit(" ", 1)
            val = float(val)
            db["fixed"].append({"name": name, "value": val})
            save_db(db)
            await update.message.reply_text("✅ Fixo salvo", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato: Netflix 39.90")
        context.user_data.clear()
        return

    # META
    if step == "goal_add":
        try:
            cat, val = text.rsplit(" ", 1)
            val = float(val)
            db["goals"].append({"category": cat, "limit": val})
            save_db(db)
            await update.message.reply_text("🎯 Meta salva", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato: iFood 300")
        context.user_data.clear()
        return

# ================= CATEGORIA =================

async def choose_category(update, context):
    q = update.callback_query
    await q.answer()

    context.user_data["category"] = q.data.replace("cat_", "")
    context.user_data["step"] = "desc"

    await q.edit_message_text("Digite a descrição:", reply_markup=back_btn())

async def new_category(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "new_cat_name"

    await q.edit_message_text("Digite nome da nova categoria:", reply_markup=back_btn())

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
        f"📊 **RELATÓRIO**\n\n"
        f"💰 Ganhos: R$ {ganho:.2f}\n"
        f"💸 Gastos: R$ {gasto:.2f}\n"
        f"📉 Saldo: R$ {saldo:.2f}\n\n"
    )

    if saldo < 0:
        msg += "⚠️ Segura o cartão 😅"

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= HISTÓRICO =================

async def history(update, context):
    q = update.callback_query
    await q.answer()

    if not db["transactions"]:
        await q.edit_message_text("Sem registros", reply_markup=main_menu())
        return

    msg = "📋 **HISTÓRICO**\n\n"
    for t in reversed(db["transactions"][-20:]):
        icon = "🔴" if t["type"] == "gasto" else "🟢"
        msg += f"{icon} {t['category']} — R$ {t['value']:.2f}\n{t['description']} ({t['date']})\n\n"

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= MAIN =================

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(start_register, pattern="^new_"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(new_category, pattern="^new_cat$"))

    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(history, pattern="^history$"))

    app.add_handler(CallbackQueryHandler(start, pattern="^start$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    asyncio.create_task(keep_alive())

    print("🤖 BOT ONLINE — OK")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())