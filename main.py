# ============================================================
# BOT FINANCEIRO MASTER — TELEGRAM — RENDER READY (FIXED)
# GANHOS • GASTOS • CATEGORIAS • METAS • RENDAS • ANÁLISES
# ============================================================

import os
import sqlite3
import logging
import sys
import io
import csv
from datetime import datetime

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
RENDA_NOME, RENDA_VALOR
) = range(10)

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

        defaults_exp = ["Alimentação", "Transporte", "Lazer", "Contas"]
        defaults_inc = ["Salário", "Extra"]

        for e in defaults_exp:
            cur.execute("INSERT INTO categories VALUES(NULL, ?, ?, 'expense')", (uid, e))

        for i in defaults_inc:
            cur.execute("INSERT INTO categories VALUES(NULL, ?, ?, 'income')", (uid, i))

        c.commit()
        return uid


def get_categories(uid, ctype):
    with db.conn() as c:
        rows = c.cursor().execute(
            "SELECT name FROM categories WHERE user_id=? AND type=?",
            (uid, ctype)
        ).fetchall()
        return [r[0] for r in rows]


def add_category(uid, name, ctype):
    with db.conn() as c:
        c.cursor().execute("INSERT INTO categories VALUES(NULL, ?, ?, ?)", (uid, name, ctype))
        c.commit()


def add_transaction(uid, t, amount, cat, desc):
    with db.conn() as c:
        c.cursor().execute(
            "INSERT INTO transactions VALUES(NULL, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (uid, t, amount, cat, desc)
        )
        c.commit()


def set_meta(uid, value):
    with db.conn() as c:
        c.cursor().execute("DELETE FROM metas WHERE user_id=?", (uid,))
        c.cursor().execute("INSERT INTO metas VALUES(NULL, ?, ?)", (uid, value))
        c.commit()


def get_meta(uid):
    with db.conn() as c:
        row = c.cursor().execute("SELECT value FROM metas WHERE user_id=?", (uid,)).fetchone()
        return row[0] if row else None


def add_renda(uid, name, value):
    with db.conn() as c:
        c.cursor().execute("INSERT INTO rendas VALUES(NULL, ?, ?, ?, CURRENT_TIMESTAMP)", (uid, name, value))
        c.commit()


def get_summary(uid):
    with db.conn() as c:
        rows = c.cursor().execute(
            "SELECT type, amount, category FROM transactions WHERE user_id=?",
            (uid,)
        ).fetchall()

    summary = {"income": 0, "expense": 0, "cats_exp": {}, "cats_inc": {}}

    for t, amount, cat in rows:
        if t == "income":
            summary["income"] += amount
            summary["cats_inc"][cat] = summary["cats_inc"].get(cat, 0) + amount
        else:
            summary["expense"] += amount
            summary["cats_exp"][cat] = summary["cats_exp"].get(cat, 0) + amount

    return summary


# ================= UI =================

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📉 Novo Gasto", callback_data="gasto"),
         InlineKeyboardButton("📈 Novo Ganho", callback_data="ganho")],

        [InlineKeyboardButton("🏷️ Nova Categoria", callback_data="addcat"),
         InlineKeyboardButton("💼 Registrar Renda", callback_data="addrenda")],

        [InlineKeyboardButton("🎯 Definir Meta", callback_data="meta")],

        [InlineKeyboardButton("📊 Análise Completa", callback_data="analise")],

        [InlineKeyboardButton("📄 Exportar CSV", callback_data="exportar")]
    ])

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_user(user.id, user.username)
    await update.message.reply_text("👋 Bot Financeiro Master ativo!", reply_markup=menu())
    return SELECT_ACTION


# ===== ANALISE COMPLETA =====

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = init_user(update.callback_query.from_user.id, update.callback_query.from_user.username)
    s = get_summary(uid)
    meta = get_meta(uid)

    msg = f"📊 <b>ANÁLISE COMPLETA</b>\n\n"
    msg += f"💰 Ganhos: R$ {s['income']:.2f}\n"
    msg += f"💸 Gastos: R$ {s['expense']:.2f}\n"
    msg += f"📈 Saldo: R$ {s['income'] - s['expense']:.2f}\n\n"

    if meta:
        msg += f"🎯 Meta: R$ {meta:.2f}\n\n"

    msg += "🔥 <b>Gastos por Categoria</b>\n"
    for k, v in sorted(s["cats_exp"].items(), key=lambda x: x[1], reverse=True):
        msg += f"- {k}: R$ {v:.2f}\n"

    msg += "\n💎 <b>Ganhos por Fonte</b>\n"
    for k, v in sorted(s["cats_inc"].items(), key=lambda x: x[1], reverse=True):
        msg += f"- {k}: R$ {v:.2f}\n"

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

    print("🤖 BOT FINANCEIRO MASTER — ONLINE — RENDER OK")
    app.run_polling(drop_pending_updates=True)
