# ===== BOT FINANCEIRO COMPLETO — TELEGRAM =====

import os
import sqlite3
import logging
import sys
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import io
import csv
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
DEL_ID,
NEW_CAT_NAME, NEW_CAT_TYPE
) = range(9)

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
        c.cursor().execute(
            "INSERT INTO categories VALUES(NULL, ?, ?, ?)",
            (uid, name, ctype)
        )
        c.commit()


def add_transaction(uid, t, amount, cat, desc):
    with db.conn() as c:
        c.cursor().execute(
            "INSERT INTO transactions VALUES(NULL, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (uid, t, amount, cat, desc)
        )
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


def get_last(uid):
    with db.conn() as c:
        return c.cursor().execute(
            "SELECT id, type, amount, category, description FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 15",
            (uid,)
        ).fetchall()


def delete_tx(uid, tid):
    with db.conn() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (tid, uid))
        c.commit()
        return cur.rowcount
