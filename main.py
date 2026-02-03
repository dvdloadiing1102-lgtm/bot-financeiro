import json
import uuid
import random
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = "COLOQUE_SEU_TOKEN_AQUI"

DB_FILE = "db.json"

# ------------------ FRASES ABSURDAS ------------------
ABSURD_PHRASES = [
    "💸 Gastando igual herdeiro, ganhando igual CLT.",
    "🫠 Seu saldo tá pedindo socorro.",
    "🔥 Isso foi gasto emocional.",
    "🤡 Compra ou pedido de ajuda?",
    "🪦 RIP dinheiro.",
    "🧠 Planejamento financeiro nível caos.",
    "🐔 Continue assim e vai jantar ovo."
]

LEVELS = [
    (0, "🪦 Falido Oficial"),
    (500, "🥲 Sobrevivente"),
    (1500, "🙂 Classe Média Iludida"),
    (5000, "😎 Bem de Vida"),
    (15000, "💼 Rico"),
    (50000, "🤑 Magnata"),
]

# ------------------ DATABASE ------------------
def load_db():
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "transactions": [],
            "categories_gain": ["Salário", "Freela"],
            "categories_expense": ["Alimentação", "Transporte", "IFood"],
            "fixed_costs": [],
            "goals": []
        }

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

db = load_db()

# ------------------ HELPERS ------------------
def get_balance():
    gain = sum(t["value"] for t in db["transactions"] if t["type"] == "ganho")
    expense = sum(t["value"] for t in db["transactions"] if t["type"] == "gasto")
    return gain, expense, gain - expense

def get_level(balance):
    lvl = LEVELS[0][1]
    for limit, name in LEVELS:
        if balance >= limit:
            lvl = name
    return lvl

def absurd_comment(value, tipo):
    if tipo == "gasto" and value > 300:
        return "🚨 GASTO ALTO! Controle-se."
    return random.choice(ABSURD_PHRASES)

# ------------------ MENUS ------------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Nova Transação", callback_data="new_trans")],
        [InlineKeyboardButton("💰 Rendas", callback_data="rendas")],
        [InlineKeyboardButton("📊 Relatório", callback_data="report")],
        [InlineKeyboardButton("📂 Categorias", callback_data="categories")],
        [InlineKeyboardButton("📌 Custos Fixos", callback_data="fixed")],
        [InlineKeyboardButton("🎯 Metas", callback_data="goals")],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data="trash")],
        [InlineKeyboardButton("💀 Modo Humilhação", callback_data="roast")]
    ])

# ------------------ START ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Financeiro ABSURDO ativado!", reply_markup=main_menu())

# ------------------ NEW TRANSACTION ------------------
async def new_trans(update, context):
    await update.callback_query.edit_message_text(
        "Tipo da transação:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Ganho", callback_data="type_gain")],
            [InlineKeyboardButton("💸 Gasto", callback_data="type_expense")]
        ])
    )

async def choose_type(update, context):
    context.user_data["type"] = "ganho" if "gain" in update.callback_query.data else "gasto"
    await update.callback_query.edit_message_text("Digite o valor:")

async def receive_value(update, context):
    try:
        value = float(update.message.text.replace(",", "."))
        context.user_data["value"] = value

        cats = db["categories_gain"] if context.user_data["type"] == "ganho" else db["categories_expense"]
        buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
        buttons.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="new_cat")])

        await update.message.reply_text("Escolha categoria:", reply_markup=InlineKeyboardMarkup(buttons))
    except:
        await update.message.reply_text("❌ Digite um número válido.")

async def select_category(update, context):
    cat = update.callback_query.data.replace("cat_", "")
    context.user_data["category"] = cat
    await update.callback_query.edit_message_text("Descrição? (ou escreva 'pular')")

async def new_category(update, context):
    await update.callback_query.edit_message_text("Digite o nome da nova categoria:")
    context.user_data["creating_cat"] = True

async def save_description(update, context):
    desc = update.message.text if update.message.text.lower() != "pular" else "Sem descrição"

    item = {
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["type"],
        "value": context.user_data["value"],
        "category": context.user_data["category"],
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    db["transactions"].append(item)
    save_db(db)

    gain, expense, balance = get_balance()
    comment = absurd_comment(item["value"], item["type"])
    level = get_level(balance)

    msg = f"""
✅ SALVO

💰 Valor: R$ {item['value']:.2f}
📂 Categoria: {item['category']}
📝 {item['description']}

🧠 {comment}

📊 Saldo: R$ {balance:.2f}
🏆 Nível: {level}
"""

    context.user_data.clear()
    await update.message.reply_text(msg, reply_markup=main_menu())

# ------------------ CATEGORIES ------------------
async def categories(update, context):
    text = "📂 Categorias:\n\n"
    text += "💰 Ganhos:\n" + "\n".join(db["categories_gain"])
    text += "\n\n💸 Gastos:\n" + "\n".join(db["categories_expense"])
    await update.callback_query.edit_message_text(text, reply_markup=main_menu())

# ------------------ REPORT ------------------
async def report(update, context):
    gain, expense, balance = get_balance()

    text = f"""
📊 RELATÓRIO

💰 Ganhos: R$ {gain:.2f}
💸 Gastos: R$ {expense:.2f}
📉 Saldo: R$ {balance:.2f}

🧾 TRANSAÇÕES:
"""

    for t in db["transactions"][-10:]:
        text += f"\n• {t['date']} | {t['category']} | R$ {t['value']:.2f}"

    await update.callback_query.edit_message_text(text, reply_markup=main_menu())

# ------------------ FIXED COSTS ------------------
async def fixed(update, context):
    text = "📌 Custos Fixos:\n"
    for c in db["fixed_costs"]:
        text += f"\n• {c['name']} - R$ {c['value']:.2f}"

    await update.callback_query.edit_message_text(
        text + "\n\nDigite nome + valor para adicionar:",
        reply_markup=main_menu()
    )
    context.user_data["adding_fixed"] = True

# ------------------ GOALS ------------------
async def goals(update, context):
    text = "🎯 Metas:\n"
    for g in db["goals"]:
        text += f"\n• {g['name']} - Limite R$ {g['limit']}"

    await update.callback_query.edit_message_text(
        text + "\n\nDigite meta + limite:",
        reply_markup=main_menu()
    )
    context.user_data["adding_goal"] = True

# ------------------ TRASH ------------------
async def trash(update, context):
    buttons = [
        [InlineKeyboardButton(f"🗑️ {t['category']} R$ {t['value']}", callback_data=f"del_{t['id']}")]
        for t in db["transactions"][-10:]
    ]

    await update.callback_query.edit_message_text(
        "🗑️ Clique para deletar:",
        reply_markup=InlineKeyboardMarkup(buttons + [[InlineKeyboardButton("⬅️ Voltar", callback_data="back")]])
    )

async def delete_item(update, context):
    id_del = update.callback_query.data.replace("del_", "")
    db["transactions"] = [t for t in db["transactions"] if t["id"] != id_del]
    save_db(db)
    await update.callback_query.answer("🗑️ Deletado!")
    await update.callback_query.edit_message_text("Deletado!", reply_markup=main_menu())

# ------------------ ROAST MODE ------------------
async def roast(update, context):
    gain, expense, balance = get_balance()
    level = get_level(balance)

    ranking = {}
    for t in db["transactions"]:
        if t["type"] == "gasto":
            ranking[t["category"]] = ranking.get(t["category"], 0) + t["value"]

    sorted_rank = sorted(ranking.items(), key=lambda x: x[1], reverse=True)

    text = f"""
💀 HUMILHAÇÃO FINANCEIRA

Saldo: R$ {balance:.2f}
Nível: {level}

🤡 TOP GASTOS QUESTIONÁVEIS:
"""

    for cat, val in sorted_rank[:5]:
        text += f"\n• {cat}: R$ {val:.2f}"

    text += "\n\n🐔 Continue assim e vai jantar ovo."

    await update.callback_query.edit_message_text(text, reply_markup=main_menu())

# ------------------ TEXT HANDLER ------------------
async def handle_text(update, context):
    text = update.message.text

    if context.user_data.get("creating_cat"):
        cat = text
        if context.user_data["type"] == "ganho":
            db["categories_gain"].append(cat)
        else:
            db["categories_expense"].append(cat)
        save_db(db)
        context.user_data.clear()
        await update.message.reply_text("✅ Categoria salva!", reply_markup=main_menu())
        return

    if context.user_data.get("adding_fixed"):
        try:
            name, value = text.rsplit(" ", 1)
            db["fixed_costs"].append({"name": name, "value": float(value)})
            save_db(db)
            context.user_data.clear()
            await update.message.reply_text("✅ Custo fixo salvo!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato: Nome VALOR")
        return

    if context.user_data.get("adding_goal"):
        try:
            name, value = text.rsplit(" ", 1)
            db["goals"].append({"name": name, "limit": float(value)})
            save_db(db)
            context.user_data.clear()
            await update.message.reply_text("✅ Meta salva!", reply_markup=main_menu())
        except:
            await update.message.reply_text("Formato: Meta VALOR")
        return

    if "value" not in context.user_data:
        await receive_value(update, context)
    elif "category" not in context.user_data:
        context.user_data["category"] = text
        await update.message.reply_text("Descrição? (ou pular)")
    else:
        await save_description(update, context)

# ------------------ MAIN ------------------
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(new_trans, pattern="new_trans"))
    app.add_handler(CallbackQueryHandler(choose_type, pattern="type_"))
    app.add_handler(CallbackQueryHandler(select_category, pattern="cat_"))
    app.add_handler(CallbackQueryHandler(new_category, pattern="new_cat"))

    app.add_handler(CallbackQueryHandler(categories, pattern="categories"))
    app.add_handler(CallbackQueryHandler(report, pattern="report"))

    app.add_handler(CallbackQueryHandler(fixed, pattern="fixed"))
    app.add_handler(CallbackQueryHandler(goals, pattern="goals"))

    app.add_handler(CallbackQueryHandler(trash, pattern="trash"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="del_"))

    app.add_handler(CallbackQueryHandler(roast, pattern="roast"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 BOT FINANCEIRO ABSURDO ONLINE")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
