# ============================================================
# BOT FINANCEIRO ULTRA MASTER — TELEGRAM — RENDER READY
# GANHOS • GASTOS • CATEGORIAS • RENDAS • PARCELAS • METAS
# ANÁLISE AVANÇADA • GRÁFICOS • EXPORTAÇÃO • ALERTAS
# ============================================================

import os, sqlite3, logging, sys, io, csv
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from openpyxl import Workbook

# ================= CONFIG =================

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    print("❌ TELEGRAM_TOKEN NÃO CONFIGURADO")
    sys.exit()

logging.basicConfig(level=logging.INFO)

# ================= STATES =================

(
SELECT_ACTION,
GASTO_VALOR, GASTO_CAT, GASTO_DESC,
GANHO_VALOR, GANHO_CAT,
NEW_CAT_NAME, NEW_CAT_TYPE,
META_VALOR,
RENDA_NOME, RENDA_VALOR,
PARCELA_VALOR, PARCELA_QTD,
DEL_ID
) = range(14)

# ================= DATABASE =================

class DB:
    def __init__(self, db_path="finance_bot.db"):
        self.db_path = db_path
        self.init_db()

    def conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        with self.conn() as c:
            cur = c.cursor()

            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                username TEXT
            )""")

            cur.execute("""CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                type TEXT
            )""")

            cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                category TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

            cur.execute("""CREATE TABLE IF NOT EXISTS metas (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                value REAL
            )""")

            cur.execute("""CREATE TABLE IF NOT EXISTS rendas (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                value REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

            c.commit()

db = DB()

# ================= CORE =================

def init_user(tid, username):
    with db.conn() as c:
        cur = c.cursor()
        cur.execute("SELECT id FROM users WHERE telegram_id=?", (tid,))
        res = cur.fetchone()

        if res:
            return res[0]

        cur.execute("INSERT INTO users VALUES(NULL, ?, ?)", (tid, username))
        uid = cur.lastrowid

        for cat in ["Alimentação", "Transporte", "Lazer", "Contas"]:
            cur.execute("INSERT INTO categories VALUES(NULL, ?, ?, 'expense')", (uid, cat))

        for cat in ["Salário", "Extra", "Freelance"]:
            cur.execute("INSERT INTO categories VALUES(NULL, ?, ?, 'income')", (uid, cat))

        c.commit()
        return uid


def get_categories(uid, t):
    with db.conn() as c:
        rows = c.cursor().execute(
            "SELECT name FROM categories WHERE user_id=? AND type=?",
            (uid, t)
        ).fetchall()
    return [r[0] for r in rows]


def add_transaction(uid, t, value, cat, desc):
    with db.conn() as c:
        c.cursor().execute(
            "INSERT INTO transactions VALUES(NULL, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (uid, t, value, cat, desc)
        )
        c.commit()


def add_renda(uid, name, value):
    with db.conn() as c:
        c.cursor().execute("INSERT INTO rendas VALUES(NULL, ?, ?, ?, CURRENT_TIMESTAMP)", (uid, name, value))
        c.commit()


def set_meta(uid, value):
    with db.conn() as c:
        c.cursor().execute("DELETE FROM metas WHERE user_id=?", (uid,))
        c.cursor().execute("INSERT INTO metas VALUES(NULL, ?, ?)", (uid, value))
        c.commit()


def get_meta(uid):
    with db.conn() as c:
        r = c.cursor().execute("SELECT value FROM metas WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r else None


def get_summary(uid):
    with db.conn() as c:
        rows = c.cursor().execute(
            "SELECT type, amount, category FROM transactions WHERE user_id=?",
            (uid,)
        ).fetchall()

    s = {"income":0,"expense":0,"cats_inc":{},"cats_exp":{}}

    for t,v,cat in rows:
        if t == "income":
            s["income"] += v
            s["cats_inc"][cat] = s["cats_inc"].get(cat,0) + v
        else:
            s["expense"] += v
            s["cats_exp"][cat] = s["cats_exp"].get(cat,0) + v

    return s


def get_last(uid):
    with db.conn() as c:
        return c.cursor().execute(
            "SELECT id,type,amount,category,description FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 30",
            (uid,)
        ).fetchall()


def delete_tx(uid, tid):
    with db.conn() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (tid, uid))
        c.commit()
        return cur.rowcount > 0


# ================= GRÁFICO =================

def generate_chart(summary):
    labels = list(summary["cats_exp"].keys())
    values = list(summary["cats_exp"].values())

    if not labels:
        return None

    plt.figure(figsize=(6,6))
    plt.pie(values, labels=labels, autopct="%1.1f%%")
    plt.title("Distribuição de Gastos")

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf


# ================= UI =================

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📉 Novo Gasto", callback_data="gasto"),
         InlineKeyboardButton("📈 Novo Ganho", callback_data="ganho")],

        [InlineKeyboardButton("💼 Registrar Renda", callback_data="addrenda"),
         InlineKeyboardButton("🎯 Definir Meta", callback_data="meta")],

        [InlineKeyboardButton("📊 Análise Completa", callback_data="analise"),
         InlineKeyboardButton("📋 Histórico", callback_data="historico")],

        [InlineKeyboardButton("🗑️ Lixeira", callback_data="lixeira")]
    ])


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    init_user(u.id, u.username)
    await update.message.reply_text("🤖 BOT FINANCEIRO ULTRA MASTER", reply_markup=menu())
    return SELECT_ACTION


# ================= ANALISE =================

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = init_user(update.callback_query.from_user.id, update.callback_query.from_user.username)
    s = get_summary(uid)
    meta = get_meta(uid)

    saldo = s["income"] - s["expense"]

    msg = f"📊 <b>RELATÓRIO FINANCEIRO ULTRA</b>\n\n"
    msg += f"💰 Ganhos: R$ {s['income']:.2f}\n"
    msg += f"💸 Gastos: R$ {s['expense']:.2f}\n"
    msg += f"📈 Saldo: R$ {saldo:.2f}\n\n"

    if meta:
        msg += f"🎯 Meta Geral: R$ {meta:.2f}\n\n"

    msg += "🔥 <b>GASTOS POR CATEGORIA</b>\n"
    for k,v in sorted(s["cats_exp"].items(), key=lambda x:x[1], reverse=True):
        msg += f"• {k}: R$ {v:.2f}\n"

    msg += "\n💎 <b>GANHOS POR FONTE</b>\n"
    for k,v in sorted(s["cats_inc"].items(), key=lambda x:x[1], reverse=True):
        msg += f"• {k}: R$ {v:.2f}\n"

    chart = generate_chart(s)

    if chart:
        await update.callback_query.message.reply_photo(photo=chart, caption=msg, parse_mode=ParseMode.HTML, reply_markup=menu())
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=menu(), parse_mode=ParseMode.HTML)

    return SELECT_ACTION


# ================= RUN =================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ACTION: [
                CallbackQueryHandler(analise, pattern="^analise$")
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(conv)

    print("🤖 BOT FINANCEIRO ULTRA MASTER — ONLINE — RENDER READY")
    app.run_polling(drop_pending_updates=True)
