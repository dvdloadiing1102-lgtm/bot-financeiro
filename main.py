import os
import json
import uuid
import asyncio
import threading
import httpx
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================

TOKEN = "COLE_SEU_TOKEN_AQUI"
RENDER_URL = os.getenv("RENDER_URL")
DB_FILE = "finance_master.json"

# ================= WEB SERVER (RENDER KEEP ALIVE) =================

def start_web_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"BOT ONLINE")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

threading.Thread(target=start_web_server, daemon=True).start()

# ================= KEEP ALIVE =================

async def keep_alive():
    if not RENDER_URL:
        return
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
        json.dump(data, f, indent=2, ensure_ascii=False)

db = load_db()

# ================= MENUS =================

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🤖 **FINANCEIRO PRO**\n\nEscolha uma opção:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

# ================= REGISTRO =================

async def start_register(update, context):
    query = update.callback_query
    await query.answer()

    tipo = query.data.replace("new_", "")
    context.user_data["type"] = tipo
    context.user_data["step"] = "value"

    await query.edit_message_text("💬 Digite o valor:\nEx: 25.50\n\n⬅️ /cancelar")

async def receive_text(update, context):
    step = context.user_data.get("step")
    text = update.message.text.strip()

    # CANCELAR
    if text.lower() == "/cancelar":
        context.user_data.clear()
        await update.message.reply_text("Cancelado.", reply_markup=main_menu())
        return

    # ===== VALOR =====
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

            await update.message.reply_text("📂 Escolha a categoria:", reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text("❌ Valor inválido. Ex: 25.50")
        return

    # ===== DESCRIÇÃO =====
    if step == "desc":
        save_transaction(context, text)
        await update.message.reply_text("✅ Registrado!", reply_markup=main_menu())
        context.user_data.clear()
        return

    # ===== NOVA CATEGORIA =====
    if step == "new_cat_name":
        tipo = context.user_data.get("type", "gasto")

        if text not in db["categories"][tipo]:
            db["categories"][tipo].append(text)
            save_db(db)

        context.user_data["category"] = text
        context.user_data["step"] = "desc"

        await update.message.reply_text("Categoria criada! Agora descrição:")
        return

    # ===== FIXOS =====
    if step == "fixed_add":
        try:
            name, val = text.rsplit(" ", 1)
            val = float(val)
            db["fixed"].append({"name": name, "value": val})
            save_db(db)
            await update.message.reply_text("✅ Custo fixo salvo!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato correto: Netflix 39.90")
        context.user_data.clear()
        return

    # ===== META =====
    if step == "goal_add":
        try:
            name, val = text.rsplit(" ", 1)
            val = float(val)
            db["goals"].append({"category": name, "limit": val})
            save_db(db)
            await update.message.reply_text("🎯 Meta criada!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato correto: iFood 300")
        context.user_data.clear()
        return

# ================= CATEGORIA =================

async def choose_category(update, context):
    query = update.callback_query
    await query.answer()

    cat = query.data.replace("cat_", "")
    context.user_data["category"] = cat
    context.user_data["step"] = "desc"

    await query.edit_message_text("📝 Digite a descrição:")

async def new_category(update, context):
    query = update.callback_query
    await query.answer()

    context.user_data["step"] = "new_cat_name"
    await query.edit_message_text("✍️ Nome da nova categoria:")

async def menu_new_cat(update, context):
    query = update.callback_query
    await query.answer()

    kb = [
        [InlineKeyboardButton("Gasto", callback_data="cat_type_gasto")],
        [InlineKeyboardButton("Ganho", callback_data="cat_type_ganho")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")]
    ]

    await query.edit_message_text("Escolha tipo da categoria:", reply_markup=InlineKeyboardMarkup(kb))

async def select_cat_type(update, context):
    query = update.callback_query
    await query.answer()

    tipo = query.data.replace("cat_type_", "")
    context.user_data["type"] = tipo
    context.user_data["step"] = "new_cat_name"

    await query.edit_message_text(f"Digite nome da categoria ({tipo}):")

# ================= SAVE =================

def save_transaction(context, desc):
    t = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["type"],
        "value": context.user_data["value"],
        "category": context.user_data["category"],
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    db["transactions"].append(t)
    save_db(db)

# ================= RELATÓRIO =================

async def report(update, context):
    query = update.callback_query
    await query.answer()

    gasto = sum(t["value"] for t in db["transactions"] if t["type"] == "gasto")
    ganho = sum(t["value"] for t in db["transactions"] if t["type"] == "ganho")
    saldo = ganho - gasto

    msg = (
        f"📊 **RELATÓRIO FINANCEIRO**\n\n"
        f"💰 Ganhos: R$ {ganho:.2f}\n"
        f"💸 Gastos: R$ {gasto:.2f}\n"
        f"📉 Saldo: R$ {saldo:.2f}\n\n"
    )

    if saldo < 0:
        msg += "⚠️ Tá gastando igual político em campanha 😅\n"

    await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= HISTÓRICO =================

async def history(update, context):
    query = update.callback_query
    await query.answer()

    if not db["transactions"]:
        await query.edit_message_text("Sem registros", reply_markup=main_menu())
        return

    msg = "📋 **HISTÓRICO**\n\n"
    for t in reversed(db["transactions"][-25:]):
        emoji = "🔴" if t["type"] == "gasto" else "🟢"
        msg += f"{emoji} {t['category']} — R$ {t['value']:.2f}\n📝 {t['description']} ({t['date']})\n\n"

    await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

# ================= FIXOS =================

async def menu_fixed(update, context):
    query = update.callback_query
    await query.answer()

    msg = "📦 **CUSTOS FIXOS**\n\n"
    if not db["fixed"]:
        msg += "Nenhum cadastrado\n"
    else:
        for f in db["fixed"]:
            msg += f"• {f['name']} — R$ {f['value']:.2f}\n"

    kb = [
        [InlineKeyboardButton("➕ Adicionar", callback_data="add_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")]
    ]

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["step"] = "fixed_add"
    await query.edit_message_text("Digite: Netflix 39.90\n⬅️ /cancelar")

# ================= METAS =================

async def menu_goals(update, context):
    query = update.callback_query
    await query.answer()

    msg = "🎯 **METAS**\n\n"
    if not db["goals"]:
        msg += "Nenhuma meta criada\n"

    for g in db["goals"]:
        gasto = sum(t["value"] for t in db["transactions"] if t["category"] == g["category"] and t["type"] == "gasto")
        pct = int((gasto / g["limit"]) * 100) if g["limit"] > 0 else 0

        msg += f"{g['category']} — {pct}% usado\n"
        if pct >= 80:
            msg += "⚠️ ALERTA: Segura o bolso 😅\n"

    kb = [
        [InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")]
    ]

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_goal(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["step"] = "goal_add"
    await query.edit_message_text("Digite: iFood 300\n⬅️ /cancelar")

# ================= LIXEIRA =================

async def trash(update, context):
    query = update.callback_query
    await query.answer()

    kb = []
    for t in reversed(db["transactions"][-10:]):
        kb.append([InlineKeyboardButton(f"❌ {t['category']} R$ {t['value']}", callback_data=f"del_{t['id']}")])

    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="start")])

    await query.edit_message_text("🗑️ Clique para apagar:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update, context):
    query = update.callback_query
    await query.answer()

    tid = query.data.replace("del_", "")
    db["transactions"] = [t for t in db["transactions"] if t["id"] != tid]
    save_db(db)

    await query.edit_message_text("✅ Apagado!", reply_markup=main_menu())

# ================= MAIN =================

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(start_register, pattern="^new_"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(new_category, pattern="^new_cat$"))

    app.add_handler(CallbackQueryHandler(menu_new_cat, pattern="^menu_new_cat$"))
    app.add_handler(CallbackQueryHandler(select_cat_type, pattern="^cat_type_"))

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

    print("🤖 BOT FINANCEIRO ONLINE")

    await app.initialize()
    await app.start()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.updater.start_polling()

    await asyncio.Event().wait()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    asyncio.get_event_loop().run_until_complete(main())
