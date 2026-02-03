import os
import sys
import subprocess
import json
import logging
import uuid
import asyncio
from datetime import datetime

# ================= AUTO-INSTALL =================
try:
    import httpx
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("⚠️ Instalando dependências...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx"])
    os.execv(sys.executable, ['python'] + sys.argv)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL")  # opcional ping externo
DB_FILE = "finance_db.json"

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================
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
    if not os.path.exists(DB_FILE):
        return default
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return default

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
    kb = [
        [InlineKeyboardButton("📝 Registrar", callback_data="reg_start")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report_quick"),
         InlineKeyboardButton("🧠 Análise Completa", callback_data="report_full")],
        [InlineKeyboardButton("📌 Fixos/Salários", callback_data="menu_fixed"),
         InlineKeyboardButton("🎯 Metas", callback_data="menu_goals")],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data="menu_delete")],
        [InlineKeyboardButton("📦 Backup", callback_data="backup_db")]
    ]
    return InlineKeyboardMarkup(kb)

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🤖 FINANCEIRO PREMIUM", reply_markup=main_menu())

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🏠 Menu Principal", reply_markup=main_menu())

# ================= REGISTRO =================
async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("📉 GASTO", callback_data="type_gasto")],
        [InlineKeyboardButton("📈 GANHO", callback_data="type_ganho")],
        [InlineKeyboardButton("⬅️ Cancelar", callback_data="main_menu")]
    ]
    await query.edit_message_text("O que deseja registrar?", reply_markup=InlineKeyboardMarkup(kb))

async def reg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["type"] = query.data.split("_")[1]
    context.user_data["step"] = "value"
    await query.edit_message_text("Digite o valor:")

async def ask_category(update, context, value_text):
    try:
        value = float(value_text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido")
        return

    context.user_data["value"] = value
    context.user_data["step"] = "category"

    tipo = context.user_data["type"]
    cats = db["categories"].get(tipo, [])

    kb = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
    kb.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])
    kb.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="main_menu")])

    await update.message.reply_text("Escolha categoria:", reply_markup=InlineKeyboardMarkup(kb))

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["category"] = query.data.replace("cat_", "")
    context.user_data["step"] = "desc"
    await query.edit_message_text("Descrição (ou envie mensagem):")

async def finish_register(update, context, desc=None):
    if update.callback_query:
        desc = update.callback_query.data.replace("desc_", "")

    item = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["type"],
        "value": context.user_data["value"],
        "category": context.user_data["category"],
        "description": desc or "Sem descrição",
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    db["transactions"].append(item)
    save_db(db)
    context.user_data.clear()

    await update.message.reply_text("✅ Registro salvo!", reply_markup=main_menu())

# ================= NOVA CATEGORIA =================
async def new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["step"] = "new_cat"
    await query.edit_message_text("Digite o nome da nova categoria:")

# ================= FIXOS =================
async def menu_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = "📌 FIXOS\n\n"
    if not db["fixed_items"]:
        text += "_Nenhum cadastrado_\n"
    else:
        for i in db["fixed_items"]:
            text += f"{i['name']} — R$ {i['value']:.2f}\n"

    kb = [
        [InlineKeyboardButton("➕ Adicionar", callback_data="add_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["step"] = "add_fixed"
    await query.edit_message_text("Formato: tipo nome valor\nEx: gasto Netflix 39")

# ================= METAS =================
async def menu_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = "🎯 METAS\n\n"
    for g in db["goals"]:
        gasto = sum(t['value'] for t in db["transactions"] if t['category'] == g['category'] and t['type'] == "gasto")
        pct = min(100, int((gasto / g['limit']) * 100))
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)

        text += f"{g['category']}\n{bar} {pct}%\nR$ {gasto:.2f}/{g['limit']:.2f}\n\n"

    kb = [
        [InlineKeyboardButton("➕ Nova Meta", callback_data="add_goal")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]
    ]

    await query.edit_message_text(text or "Nenhuma meta", reply_markup=InlineKeyboardMarkup(kb))

async def add_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["step"] = "add_goal"
    await query.edit_message_text("Formato: categoria valor\nEx: Lazer 500")

# ================= RELATÓRIOS =================
async def report_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    ganho = sum(t['value'] for t in db["transactions"] if t['type'] == "ganho")
    gasto = sum(t['value'] for t in db["transactions"] if t['type'] == "gasto")

    saldo = ganho - gasto

    text = f"""
📊 RELATÓRIO

💰 Ganhos: R$ {ganho:.2f}
💸 Gastos: R$ {gasto:.2f}

📈 Saldo: R$ {saldo:.2f}
"""

    await query.edit_message_text(text, reply_markup=main_menu())

async def report_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = "📜 HISTÓRICO\n\n"
    for t in reversed(db["transactions"][-15:]):
        icon = "🔴" if t['type'] == "gasto" else "🟢"
        text += f"{icon} {t['category']} — R$ {t['value']} — {t['description']}\n"

    await query.edit_message_text(text or "Sem registros", reply_markup=main_menu())

# ================= DELETE =================
async def menu_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = [
        [InlineKeyboardButton("💲 Apagar Transação", callback_data="del_trans")],
        [InlineKeyboardButton("📌 Apagar Fixos", callback_data="del_fixed")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")]
    ]

    await query.edit_message_text("🗑️ Escolha o que apagar", reply_markup=InlineKeyboardMarkup(kb))

async def del_trans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = []
    for t in reversed(db["transactions"][-10:]):
        kb.append([InlineKeyboardButton(f"❌ {t['category']} R$ {t['value']}", callback_data=f"kill_{t['id']}")])

    kb.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_delete")])

    await query.edit_message_text("Apagar transação:", reply_markup=InlineKeyboardMarkup(kb))

async def kill_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t["id"] != tid]
    save_db(db)

    await query.edit_message_text("✅ Apagado!", reply_markup=main_menu())

# ================= BACKUP =================
async def backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await update.effective_message.reply_document(open(DB_FILE, "rb"), caption="📦 Backup")

# ================= TEXT HANDLER =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    txt = update.message.text

    if step == "value":
        await ask_category(update, context, txt)
        return

    if step == "desc":
        await finish_register(update, context, txt)
        return

    if step == "new_cat":
        tipo = context.user_data.get("type", "gasto")
        db["categories"][tipo].append(txt)
        save_db(db)
        await update.message.reply_text("✅ Categoria criada!")
        context.user_data["step"] = "desc"
        return

    if step == "add_fixed":
        try:
            p = txt.split()
            tipo = p[0]
            valor = float(p[-1].replace(",", "."))
            nome = " ".join(p[1:-1])

            db["fixed_items"].append({"type": tipo, "name": nome, "value": valor})
            save_db(db)
            await update.message.reply_text("✅ Fixo salvo!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Erro. Ex: gasto Netflix 39")

        context.user_data.clear()
        return

    if step == "add_goal":
        try:
            cat, val = txt.rsplit(" ", 1)
            db["goals"].append({"category": cat, "limit": float(val)})
            save_db(db)
            await update.message.reply_text("🎯 Meta criada!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Erro. Ex: Lazer 500")

        context.user_data.clear()
        return

# ================= INIT =================
async def post_init(app):
    if RENDER_URL:
        asyncio.create_task(keep_alive())

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(back_menu, pattern="^main_menu$"))

    app.add_handler(CallbackQueryHandler(reg_start, pattern="^reg_start$"))
    app.add_handler(CallbackQueryHandler(reg_type, pattern="^type_"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(new_cat, pattern="^new_cat$"))

    app.add_handler(CallbackQueryHandler(menu_fixed, pattern="^menu_fixed$"))
    app.add_handler(CallbackQueryHandler(add_fixed, pattern="^add_fixed$"))

    app.add_handler(CallbackQueryHandler(menu_goals, pattern="^menu_goals$"))
    app.add_handler(CallbackQueryHandler(add_goal, pattern="^add_goal$"))

    app.add_handler(CallbackQueryHandler(report_quick, pattern="^report_quick$"))
    app.add_handler(CallbackQueryHandler(report_full, pattern="^report_full$"))

    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(del_trans, pattern="^del_trans$"))
    app.add_handler(CallbackQueryHandler(kill_item, pattern="^kill_"))

    app.add_handler(CallbackQueryHandler(backup_db, pattern="^backup_db$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 BOT FINANCEIRO ONLINE")
    app.run_polling()
