Aimport os
import json
import logging
import uuid
import random
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ConversationHandler
)

import google.generativeai as genai

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN") or "8314300130:AAGLrTqIZDpPbWug-Rtj6sa0LpPCK15e6qI"
GEMINI_KEY = os.getenv("GEMINI_KEY") or "COLOQUE_SUA_KEY"
DB_FILE = "finance_v15_data.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

genai.configure(api_key=GEMINI_KEY)
model_ai = genai.GenerativeModel("gemini-1.5-flash")

# ================= DB =================
DEFAULT_DB = {
    "transactions": [],
    "categories": {
        "ganho": ["Salário", "Extra"],
        "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa"]
    },
    "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter"],
    "fixed": [],
    "goals": [],
    "config": {"zoeiro_mode": False}
}

def load_db():
    if not os.path.exists(DB_FILE):
        return DEFAULT_DB.copy()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Erro ao carregar DB: {e}")
        return DEFAULT_DB.copy()

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

db = load_db()

# ================= UTIL =================
def now_month():
    return datetime.now().strftime("%m/%Y")

def money(x):
    return f"R$ {x:.2f}"

# ================= ZOEIRA MODERADA =================
ZOEIRA_GASTOS = [
    "💸 Gastou bonito hein, Elon Musk do Bangu",
    "🤡 Seu dinheiro foi de base",
    "😭 Mais um golpe no orçamento",
    "🛑 Banco Central sentiu essa",
    "💀 RIP saldo"
]

ZOEIRA_GANHOS = [
    "🤑 Tá rico ou é impressão?",
    "🔥 Dinheiro entrando, chama o contador",
    "👑 Rei do PIX",
    "💰 Receita digna de CEO",
    "🚀 Saldo subindo igual foguete"
]

ZOEIRA_SALDO = [
    "⚖️ Saldo equilibrado… milagre?",
    "🧘 Financeiramente zen",
    "📉 Segura esse rombo",
    "📈 Tá respirando ainda",
    "💎 Sobrevivendo como um guerreiro"
]

def zoeira(tipo):
    if not db["config"]["zoeiro_mode"]:
        return ""
    if tipo == "gasto":
        return random.choice(ZOEIRA_GASTOS)
    if tipo == "ganho":
        return random.choice(ZOEIRA_GANHOS)
    return random.choice(ZOEIRA_SALDO)

# ================= CÁLCULOS =================
def calculate_balance():
    mes = now_month()

    ganhos_fixos = sum(f["value"] for f in db["fixed"] if f["type"] == "ganho")
    gastos_fixos = sum(f["value"] for f in db["fixed"] if f["type"] == "gasto")

    trans_mes = [t for t in db["transactions"] if mes in t["date"]]

    ganhos = sum(t["value"] for t in trans_mes if t["type"] == "ganho")
    gastos = sum(t["value"] for t in trans_mes if t["type"] == "gasto")

    total_in = ganhos_fixos + ganhos
    total_out = gastos_fixos + gastos
    saldo = total_in - total_out

    return saldo, total_in, total_out

# ================= MENU PRINCIPAL =================
async def start(update, context):
    context.user_data.clear()

    saldo, entradas, saidas = calculate_balance()
    zoeira_txt = zoeira("saldo")

    mode_txt = "🤡 Zoeiro: ON" if db["config"]["zoeiro_mode"] else "🤖 Modo: Sério"

    keyboard = [
        [
            InlineKeyboardButton("📝 REGISTRAR", callback_data="start_reg"),
            InlineKeyboardButton("🔍 RAIO-X", callback_data="full_report")
        ],
        [
            InlineKeyboardButton("📌 FIXOS", callback_data="menu_fixed"),
            InlineKeyboardButton("🧠 COACH IA", callback_data="ai_coach")
        ],
        [
            InlineKeyboardButton("📊 GRÁFICO", callback_data="chart_pie"),
            InlineKeyboardButton("📄 PDF", callback_data="export_pdf")
        ],
        [
            InlineKeyboardButton("➕ CATEGORIA", callback_data="menu_cat"),
            InlineKeyboardButton("🗑️ EXCLUIR", callback_data="menu_delete")
        ],
        [
            InlineKeyboardButton("📂 CSV", callback_data="export_csv"),
            InlineKeyboardButton(mode_txt, callback_data="toggle_mode")
        ]
    ]

    text = (
        "🤖 **FINANCEIRO V15**\n\n"
        f"💰 **Saldo Real:** {money(saldo)}\n"
        f"{zoeira_txt}\n\n"
        f"📈 Ganhos: {money(entradas)}\n"
        f"📉 Gastos: {money(saidas)}"
    )

    msg = update.callback_query.message if update.callback_query else update.message
    send = msg.edit_text if update.callback_query else msg.reply_text

    await send(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

# ================= TOGGLE ZOEIRA =================
async def toggle_mode(update, context):
    query = update.callback_query
    await query.answer()

    db["config"]["zoeiro_mode"] = not db["config"]["zoeiro_mode"]
    save_db(db)

    return await start(update, context)

# ================= RAIO-X =================
async def full_report(update, context):
    query = update.callback_query
    await query.answer()

    mes = now_month()
    saldo, entradas, saidas = calculate_balance()

    gastos_mes = [
        t for t in db["transactions"]
        if mes in t["date"] and t["type"] == "gasto"
    ]

    categorias = {}
    for t in gastos_mes:
        categorias[t["category"]] = categorias.get(t["category"], 0) + t["value"]

    msg = (
        f"🔍 **RAIO-X ({mes})**\n\n"
        f"📈 Entradas: {money(entradas)}\n"
        f"📉 Saídas: {money(saidas)}\n"
        f"⚖️ **Saldo: {money(saldo)}**\n\n"
        "**📌 GASTOS POR CATEGORIA:**\n"
    )

    for cat, val in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
        msg += f"🔸 {cat}: {money(val)}\n"

    if db["config"]["zoeiro_mode"]:
        msg += f"\n🤡 {zoeira('gasto')}\n"

    await query.edit_text(
        msg,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Voltar", callback_data="cancel")]
        ]),
        parse_mode="Markdown"
    )

# ================= EXCLUIR =================
async def menu_delete(update, context):
    query = update.callback_query
    await query.answer()

    ultimos = list(reversed(db["transactions"][-5:]))

    keyboard = [
        [InlineKeyboardButton(
            f"❌ {money(t['value'])} - {t['category']}",
            callback_data=f"kill_{t['id']}"
        )]
        for t in ultimos
    ]

    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data="cancel")])

    await query.edit_text(
        "🗑️ **Apagar qual item?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def delete_item(update, context):
    query = update.callback_query
    await query.answer()

    tid = query.data.replace("kill_", "")

    db["transactions"] = [t for t in db["transactions"] if t["id"] != tid]
    save_db(db)

    return await start(update, context)

async def cancel(update, context):
    return await start(update, context)

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(toggle_mode, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(full_report, pattern="^full_report$"))
    app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete$"))
    app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))

    print("🚀 FINANCEIRO V15 ONLINE — ZOEIRA MODERADA ATIVA")
    app.run_polling(drop_pending_updates=True)