import os
import json
import uuid
import asyncio
import logging
from datetime import datetime
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_FILE = "finance_absurdo.json"
RENDER_URL = os.getenv("RENDER_URL")

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================

def load_db():
    default = {
        "transactions": [],
        "categories": {
            "gasto": ["Alimentação", "Transporte", "Lazer", "Casa", "iFood"],
            "ganho": ["Salário", "Extra"]
        },
        "fixed": [],
        "goals": []
    }
    if not os.path.exists(DB_FILE):
        return default
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

db = load_db()

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

# ================= MENUS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Registrar", callback_data="reg_start")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report")],
        [InlineKeyboardButton("📌 Fixos", callback_data="fixed_menu"),
         InlineKeyboardButton("🎯 Metas", callback_data="goal_menu")],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data="trash_menu")],
        [InlineKeyboardButton("📦 Backup", callback_data="backup")]
    ])

def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="menu")]])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🤖 **FINANCEIRO ABSURDO PRO**\nSeu gerente financeiro debochado 💸",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("🏦 Menu Principal", reply_markup=main_menu())

# ================= REGISTRO =================

async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📉 Gasto", callback_data="type_gasto")],
        [InlineKeyboardButton("📈 Ganho", callback_data="type_ganho")],
        [InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")]
    ]
    await update.callback_query.edit_message_text("O que vai registrar?", reply_markup=InlineKeyboardMarkup(kb))

async def reg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.callback_query.data.split("_")[1]
    context.user_data["type"] = t
    context.user_data["step"] = "value"
    emoji = "💸" if t == "gasto" else "💰"
    await update.callback_query.edit_message_text(f"{emoji} Digite o valor:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    txt = update.message.text.strip()

    # VALOR
    if step == "value":
        try:
            value = float(txt.replace(",", "."))
        except:
            await update.message.reply_text("❌ Valor inválido, tenta de novo.")
            return
        
        context.user_data["value"] = value
        context.user_data["step"] = "category"

        cats = db["categories"][context.user_data["type"]]
        kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
        kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])
        await update.message.reply_text("Escolha categoria:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # NOVA CATEGORIA
    if step == "new_cat_name":
        cat = txt
        t = context.user_data["type"]
        db["categories"][t].append(cat)
        save_db(db)

        context.user_data["category"] = cat
        context.user_data["step"] = "desc"
        await update.message.reply_text(f"Categoria **{cat}** criada 🎉\nDigite descrição:")
        return

    # DESCRIÇÃO
    if step == "desc":
        t = context.user_data["type"]
        val = context.user_data["value"]
        cat = context.user_data["category"]
        desc = txt

        item = {
            "id": str(uuid.uuid4())[:8],
            "type": t,
            "value": val,
            "category": cat,
            "desc": desc,
            "date": datetime.now().strftime("%d/%m/%Y %H:%M")
        }

        db["transactions"].append(item)
        save_db(db)

        zoeira = ""
        if t == "gasto" and val > 200:
            zoeira = "\n😈 Gastando assim vai almoçar miojo esse mês."

        await update.message.reply_text(
            f"✅ Registrado!\n{('➖' if t=='gasto' else '➕')} R$ {val:.2f}\n📂 {cat}\n📝 {desc}{zoeira}",
            reply_markup=main_menu()
        )
        context.user_data.clear()
        return

    # FIXO
    if step == "fixed_add":
        try:
            parts = txt.rsplit(" ", 1)
            name = parts[0]
            val = float(parts[1].replace(",", "."))
            db["fixed"].append({"name": name, "value": val})
            save_db(db)
            await update.message.reply_text("📌 Fixo cadastrado!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato errado. Ex: Netflix 45")
        context.user_data.clear()
        return

    # META
    if step == "goal_add":
        try:
            parts = txt.rsplit(" ", 1)
            cat = parts[0]
            limit = float(parts[1].replace(",", "."))
            db["goals"].append({"category": cat, "limit": limit})
            save_db(db)
            await update.message.reply_text("🎯 Meta salva!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Ex: Alimentação 500")
        context.user_data.clear()
        return

# ================= CALLBACKS =================

async def select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = update.callback_query.data.replace("cat_", "")
    context.user_data["category"] = cat
    context.user_data["step"] = "desc"
    await update.callback_query.edit_message_text("Digite descrição:")

async def new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "new_cat_name"
    await update.callback_query.edit_message_text("Digite nome da nova categoria:")

# ================= FIXOS =================

async def fixed_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📌 FIXOS:\n\n"
    for f in db["fixed"]:
        text += f"• {f['name']} — R$ {f['value']:.2f}\n"
    kb = [
        [InlineKeyboardButton("➕ Adicionar", callback_data="fixed_add")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def fixed_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "fixed_add"
    await update.callback_query.edit_message_text("Digite: Nome Valor\nEx: Netflix 45")

# ================= METAS =================

async def goal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🎯 METAS:\n\n"
    for g in db["goals"]:
        gasto = sum(t["value"] for t in db["transactions"] if t["category"] == g["category"] and t["type"] == "gasto")
        pct = int((gasto / g["limit"]) * 100) if g["limit"] > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)

        alerta = ""
        if pct > 80:
            alerta = "\n⚠️ Cuidado: já tá quase virando monge financeiro."

        text += f"📂 {g['category']}\n{bar} {pct}%\nR$ {gasto:.2f} / {g['limit']:.2f}{alerta}\n\n"

    kb = [
        [InlineKeyboardButton("➕ Nova Meta", callback_data="goal_add")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def goal_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "goal_add"
    await update.callback_query.edit_message_text("Digite: Categoria Valor\nEx: Lazer 300")

# ================= RELATÓRIO =================

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc = sum(t["value"] for t in db["transactions"] if t["type"] == "ganho")
    exp = sum(t["value"] for t in db["transactions"] if t["type"] == "gasto")
    saldo = inc - exp

    zoeira = ""
    if saldo < 0:
        zoeira = "\n💀 Saldo negativo. Vai parcelar o oxigênio."
    elif saldo < 100:
        zoeira = "\n🥚 Saldo de estudante universitário."

    text = (
        f"📊 RELATÓRIO GERAL\n\n"
        f"💰 Ganhos: R$ {inc:.2f}\n"
        f"💸 Gastos: R$ {exp:.2f}\n"
        f"📉 Saldo: R$ {saldo:.2f}{zoeira}"
    )

    await update.callback_query.edit_message_text(text, reply_markup=main_menu())

# ================= LIXEIRA =================

async def trash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🧾 Deletar Transação", callback_data="trash_trans")],
        [InlineKeyboardButton("📌 Deletar Fixo", callback_data="trash_fixed")],
        [InlineKeyboardButton("🎯 Deletar Meta", callback_data="trash_goal")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu")]
    ]
    await update.callback_query.edit_message_text("🗑️ LIXEIRA", reply_markup=InlineKeyboardMarkup(kb))

async def trash_trans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = []
    for t in db["transactions"][-10:]:
        kb.append([InlineKeyboardButton(f"❌ {t['category']} R$ {t['value']}", callback_data=f"del_{t['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="trash_menu")])
    await update.callback_query.edit_message_text("Apagar transação:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.callback_query.data.replace("del_", "")
    db["transactions"] = [t for t in db["transactions"] if t["id"] != tid]
    save_db(db)
    await update.callback_query.edit_message_text("✅ Apagado!", reply_markup=main_menu())

# ================= BACKUP =================

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_document(open(DB_FILE, "rb"))

# ================= RUN =================

if __name__ == "__main__":
    if RENDER_URL:
        asyncio.create_task(keep_alive())

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(menu, pattern="^menu$"))

    app.add_handler(CallbackQueryHandler(reg_start, pattern="^reg_start$"))
    app.add_handler(CallbackQueryHandler(reg_type, pattern="^type_"))
    app.add_handler(CallbackQueryHandler(select_cat, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(new_cat, pattern="^new_cat$"))

    app.add_handler(CallbackQueryHandler(fixed_menu, pattern="^fixed_menu$"))
    app.add_handler(CallbackQueryHandler(fixed_add, pattern="^fixed_add$"))

    app.add_handler(CallbackQueryHandler(goal_menu, pattern="^goal_menu$"))
    app.add_handler(CallbackQueryHandler(goal_add, pattern="^goal_add$"))

    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))

    app.add_handler(CallbackQueryHandler(trash_menu, pattern="^trash_menu$"))
    app.add_handler(CallbackQueryHandler(trash_trans, pattern="^trash_trans$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^del_"))

    app.add_handler(CallbackQueryHandler(backup, pattern="^backup$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 FINANCEIRO ABSURDO ONLINE")
    app.run_polling()
