import os
import sqlite3
import re
import threading
import logging
from datetime import datetime
from dataclasses import dataclass
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURAÇÃO ---
# SEU TOKEN ESTÁ AQUI DIRETO (Para garantir que funciona):
TELEGRAM_TOKEN = "8314300130:AAGBQJ_7peneVciiSHJxf1E5f-CZbVc7XsU"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- BANCO DE DADOS E LÓGICA ---

class FinanceDatabase:
    def __init__(self, db_path="finance_bot.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, username TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT, amount REAL, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    def get_user_id(self, telegram_id, username):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            res = c.fetchone()
            if res: return res[0]
            c.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
            return c.lastrowid

class FinanceBot:
    def __init__(self, db_path="finance_bot.db"):
        self.db = FinanceDatabase(db_path)

    def initialize_user(self, telegram_id, username):
        uid = self.db.get_user_id(telegram_id, username)
        with sqlite3.connect(self.db.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM categories WHERE user_id = ?", (uid,))
            if not c.fetchone():
                cats = ["Alimentacao", "Transporte", "Lazer", "Salario", "Contas"]
                for name in cats: c.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))
        return uid

    def add_transaction(self, uid, type_, amount, category, desc):
        with sqlite3.connect(self.db.db_path) as conn:
            conn.cursor().execute("INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)", (uid, type_, amount, category, desc))

    def get_summary(self, uid):
        with sqlite3.connect(self.db.db_path) as conn:
            rows = conn.cursor().execute("SELECT type, amount, category FROM transactions WHERE user_id = ?", (uid,)).fetchall()
        summary = {"income": 0, "expense": 0, "cats": {}}
        for type_, amount, cat in rows:
            if type_ == "income": summary["income"] += amount
            else: summary["expense"] += amount
            if cat not in summary["cats"]: summary["cats"][cat] = 0
            summary["cats"][cat] += amount
        return summary

    def export_pdf(self, uid, filename):
        summary = self.get_summary(uid)
        doc = SimpleDocTemplate(filename, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph("Relatorio Financeiro", styles['Heading1']))
        elements.append(Spacer(1, 0.2*25)) 
        
        data = [["Resumo", "Valor"], ["Ganhos", f"R$ {summary['income']:.2f}"], ["Gastos", f"R$ {summary['expense']:.2f}"], ["Saldo", f"R$ {summary['income'] - summary['expense']:.2f}"]]
        t = Table(data)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.grey)]))
        elements.append(t)
        elements.append(Spacer(1, 0.2*25))
        
        cat_data = [["Categoria", "Total"]]
        for k, v in summary["cats"].items():
            clean_k = re.sub(r'[^\w\s]', '', k) 
            cat_data.append([clean_k, f"R$ {v:.2f}"])
        t2 = Table(cat_data)
        t2.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black)]))
        elements.append(t2)
        doc.build(elements)

# --- TELEGRAM HANDLERS ---
bot_logic = FinanceBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_logic.initialize_user(user.id, user.username)
    msg = (f"👋 Olá {user.first_name}!\n\n💸 **COMANDOS:**\n`/gasto 50.00 Mercado`\n`/ganho 2000.00 Salario`\n`/extrato`\n`/pdf`")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        cat = context.args[1] if len(context.args) > 1 else "Geral"
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "expense", val, cat, "Gasto")
        await update.message.reply_text(f"✅ Gasto de R$ {val:.2f} em {cat} salvo!")
    except: await update.message.reply_text("❌ Use: `/gasto 50.00 Mercado`", parse_mode='Markdown')

async def ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "income", val, "Salario", "Ganho")
        await update.message.reply_text(f"✅ Ganho de R$ {val:.2f} salvo!")
    except: await update.message.reply_text("❌ Use: `/ganho 2000.00`", parse_mode='Markdown')

async def extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    s = bot_logic.get_summary(uid)
    msg = f"📊 **RESUMO**\n\n💰 Entrou: R$ {s['income']:.2f}\n💸 Saiu: R$ {s['expense']:.2f}\n🟢 Saldo: R$ {s['income'] - s['expense']:.2f}"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Gerando PDF...")
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    fname = f"relatorio_{uid}.pdf"
    try:
        bot_logic.export_pdf(uid, fname)
        await update.message.reply_document(open(fname, 'rb'))
        os.remove(fname)
        await msg.delete()
    except Exception as e: await msg.edit_text(f"Erro: {e}")

# --- SERVIDOR WEB (RENDER) ---
app = Flask(__name__)
@app.route('/')
def home(): return "🤖 Bot Financeiro Online e com Token!"
def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    ApplicationBuilder().token(TELEGRAM_TOKEN).build().run_polling()
