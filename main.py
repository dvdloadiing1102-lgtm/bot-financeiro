# ==== MESMO IMPORTS DO SEU CÓDIGO ====
import os
import json
import uuid
import asyncio
import threading
import httpx
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI"
RENDER_URL = os.getenv("RENDER_URL")
DB_FILE = "finance_master.json"

# ================= WEB SERVER =================
def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=start_web_server, daemon=True).start()

# ================= KEEP ALIVE =================
async def keep_alive():
    if not RENDER_URL:
        return
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(600)
            try:
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
        return json.load(open(DB_FILE))
    except:
        return default

def save_db(data):
    json.dump(data, open(DB_FILE, "w"), indent=2)

db = load_db()

# ================= MENU =================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Novo Gasto", callback_data="new_gasto"),
         InlineKeyboardButton("💰 Novo Ganho", callback_data="new_ganho")],
        [InlineKeyboardButton("📦 Custos Fixos", callback_data="menu_fixed"),
         InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report"),
         InlineKeyboardButton("📋 Histórico", callback_data="history")],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data="trash")],
        [InlineKeyboardButton("➕ Nova Categoria", callback_data="menu_new_cat")]
    ])

# ================= START =================
async def start(update, context):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.edit_message_text("🤖 FINANCEIRO PRO\nEscolha:", reply_markup=main_menu())
    else:
        await update.message.reply_text("🤖 FINANCEIRO PRO\nEscolha:", reply_markup=main_menu())

# ================= REGISTRO =================
async def start_register(update, context):
    q = update.callback_query
    await q.answer()
    tipo = q.data.replace("new_", "")
    context.user_data["type"] = tipo
    context.user_data["step"] = "value"
    await q.edit_message_text("💬 Digite o valor:\nEx: 25.50\n\n⬅️ Digite /start para voltar")

async def receive_text(update, context):
    step = context.user_data.get("step")
    text = update.message.text

    # VALOR
    if step == "value":
        try:
            val = float(text.replace(",", "."))
            context.user_data["value"] = val
            context.user_data["step"] = "category"
            tipo = context.user_data["type"]

            kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in db["categories"][tipo]]
            kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat_flow")])
            kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="start")])

            await update.message.reply_text("📂 Escolha categoria:", reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text("❌ Valor inválido")
        return

    # NOVA CATEGORIA (FLOW)
    if step == "new_cat_name":
        tipo = context.user_data.get("type", "gasto")
        db["categories"][tipo].append(text)
        save_db(db)
        context.user_data["category"] = text
        context.user_data["step"] = "desc"
        await update.message.reply_text("✅ Categoria criada! Digite descrição:")
        return

    # DESCRIÇÃO
    if step == "desc":
        save_transaction(context, text)
        context.user_data.clear()
        await update.message.reply_text("✅ Registrado!", reply_markup=main_menu())
        return

    # FIXO
    if step == "fixed_add":
        try:
            name, val = text.rsplit(" ", 1)
            db["fixed"].append({"name": name, "value": float(val)})
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
            db["goals"].append({"category": cat, "limit": float(val)})
            save_db(db)
            await update.message.reply_text("🎯 Meta criada!", reply_markup=main_menu())
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
    await q.edit_message_text("📝 Digite descrição:")

async def new_category_flow(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "new_cat_name"
    await q.edit_message_text("✍️ Nome da nova categoria:")

async def menu_new_cat(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "new_cat_name"
    await q.edit_message_text("✍️ Nome da nova categoria:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")]
    ]))

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

    msg = f"📊 RELATÓRIO\n\n💰 Ganhos: R$ {ganho:.2f}\n💸 Gastos: R$ {gasto:.2f}\n📉 Saldo: R$ {saldo:.2f}"
    await q.edit_message_text(msg, reply_markup=main_menu())

# ================= HISTÓRICO =================
async def history(update, context):
    q = update.callback_query
    await q.answer()

    if not db["transactions"]:
        await q.edit_message_text("Sem registros", reply_markup=main_menu())
        return

    msg = "📋 HISTÓRICO\n\n"
    for t in reversed(db["transactions"][-25:]):
        emoji = "🔴" if t["type"] == "gasto" else "🟢"
        msg += f"{emoji} {t['category']} — R$ {t['value']:.2f}\n{t['description']}\n\n"

    await q.edit_message_text(msg, reply_markup=main_menu())

# ================= FIXOS =================
async def menu_fixed(update, context):
    q = update.callback_query
    await q.answer()

    msg = "📦 FIXOS\n\n"
    msg += "\n".join([f"{f['name']} — R$ {f['value']:.2f}" for f in db["fixed"]]) or "Nenhum"

    kb = [
        [InlineKeyboardButton("➕ Adicionar", callback_data="add_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")]
    ]

    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def add_fixed(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "fixed_add"
    await q.edit_message_text("Digite: Netflix 39.90")

# ================= METAS =================
async def menu_goals(update, context):
    q = update.callback_query
    await q.answer()

    msg = "🎯 METAS\n\n"
    for g in db["goals"]:
        gasto = sum(t["value"] for t in db["transactions"] if t["category"] == g["category"])
        pct = int((gasto / g["limit"]) * 100) if g["limit"] > 0 else 0
        msg += f"{g['category']} — {pct}% usado\n"

    kb = [
        [InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")]
    ]

    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def add_goal(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["step"] = "goal_add"
    await q.edit_message_text("Digite: iFood 300")

# ================= LIXEIRA =================
async def trash(update, context):
    q = update.callback_query
    await q.answer()

    kb = [[InlineKeyboardButton(f"❌ {t['category']} R$ {t['value']}", callback_data=f"del_{t['id']}")]
          for t in reversed(db["transactions"][-10:])]

    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="start")])

    await q.edit_message_text("🗑️ Clique para apagar:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update, context):
    q = update.callback_query
    await q.answer()

    tid = q.data.replace("del_", "")
    db["transactions"] = [t for t in db["transactions"] if t["id"] != tid]
    save_db(db)

    await q.edit_message_text("✅ Apagado!", reply_markup=main_menu())

# ================= MAIN =================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(start_register, pattern="^new_"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(new_category_flow, pattern="^new_cat_flow$"))
    app.add_handler(CallbackQueryHandler(menu_new_cat, pattern="^menu_new_cat$"))

    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(history, pattern="^history$"))

    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(add_fixed, pattern="^add_fixed$"))

    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(add_goal, pattern="^add_goal$"))

    app.add_handler(CallbackQueryHandler(trash, pattern="^trash$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^del_"))

    app.add_handler(CallbackQueryHandler(start, pattern="^start$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    asyncio.create_task(keep_alive())

    print("🤖 BOT FINANCEIRO — OPERACIONAL")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())