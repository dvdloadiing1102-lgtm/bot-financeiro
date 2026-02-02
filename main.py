import os
import sqlite3
import threading
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- SEU TOKEN (O VÁLIDO QUE TERMINA EM SSFYc) ---
TELEGRAM_TOKEN = "8314300130:AAGFjGNp6L6n_8TmvvKIvOsP0bLmX_SSFYc"

# Configuração de Logs (Para pegarmos qualquer erro)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- BANCO DE DADOS (Com proteção de Thread) ---
class FinanceDatabase:
    def __init__(self, db_path="finance_bot.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        # Permite conexões de threads diferentes (Flask vs Telegram)
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, username TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT, amount REAL, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    def get_user_id(self, telegram_id, username):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            res = c.fetchone()
            if res: return res[0]
            c.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username or "SemNome"))
            return c.lastrowid

# --- LÓGICA DO BOT ---
class FinanceBot:
    def __init__(self, db_path="finance_bot.db"):
        self.db = FinanceDatabase(db_path)

    def initialize_user(self, telegram_id, username):
        uid = self.db.get_user_id(telegram_id, username)
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM categories WHERE user_id = ?", (uid,))
            if not c.fetchone():
                cats = ["Alimentacao", "Transporte", "Lazer", "Salario", "Contas"]
                for name in cats: c.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))
        return uid

    def add_transaction(self, uid, type_, amount, category, desc):
        with self.db.get_connection() as conn:
            conn.cursor().execute("INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)", (uid, type_, amount, category, desc))

    def get_summary(self, uid):
        with self.db.get_connection() as conn:
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
        elements.append(Paragraph("Relatório Financeiro", styles['Heading1']))
        elements.append(Spacer(1, 20))
        
        data = [["Resumo", "Valor"], ["Ganhos", f"R$ {summary['income']:.2f}"], ["Gastos", f"R$ {summary['expense']:.2f}"], ["Saldo", f"R$ {summary['income'] - summary['expense']:.2f}"]]
        t = Table(data)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        elements.append(t)
        doc.build(elements)

bot_logic = FinanceBot()

# --- COMANDOS DO TELEGRAM (USANDO HTML) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_logic.initialize_user(user.id, user.username)
    # HTML é mais seguro que Markdown para nomes com caracteres estranhos
    msg = (f"Olá <b>{user.first_name}</b>!\n\n"
           f"💰 <b>COMANDOS:</b>\n"
           f"/gasto 50.00 Mercado\n"
           f"/ganho 2000.00 Salario\n"
           f"/extrato\n"
           f"/pdf")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        cat = context.args[1] if len(context.args) > 1 else "Geral"
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "expense", val, cat, "Gasto")
        await update.message.reply_text(f"✅ Gasto de <b>R$ {val:.2f}</b> em <i>{cat}</i> salvo!", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("❌ Use assim: <code>/gasto 50.00 Mercado</code>", parse_mode=ParseMode.HTML)

async def ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "income", val, "Salario", "Ganho")
        await update.message.reply_text(f"✅ Ganho de <b>R$ {val:.2f}</b> salvo!", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("❌ Use assim: <code>/ganho 2000.00</code>", parse_mode=ParseMode.HTML)

async def extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    s = bot_logic.get_summary(uid)
    saldo = s['income'] - s['expense']
    cor_saldo = "🟢" if saldo >= 0 else "🔴"
    msg = (f"📊 <b>RESUMO</b>\n\n"
           f"💰 Entrou: R$ {s['income']:.2f}\n"
           f"💸 Saiu: R$ {s['expense']:.2f}\n"
           f"{cor_saldo} <b>Saldo: R$ {saldo:.2f}</b>")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Gerando PDF...")
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    fname = f"relatorio_{uid}.pdf"
    try:
        bot_logic.export_pdf(uid, fname)
        await update.message.reply_document(open(fname, 'rb'))
        os.remove(fname)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Erro: {e}")

# --- SERVIDOR WEB (FLASK) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Financeiro Rodando em HTML Mode! Status: ONLINE."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- INICIALIZAÇÃO DO BOT ---
if __name__ == '__main__':
    # 1. Inicia o Flask em uma thread separada para o Render não reclamar
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # 2. Configura e Roda o Bot (POLLING)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gasto", gasto))
    application.add_handler(CommandHandler("ganho", ganho))
    application.add_handler(CommandHandler("extrato", extrato))
    application.add_handler(CommandHandler("pdf", pdf))

    # Comando para limpar qualquer webhook preso e forçar o polling
    print("Iniciando Polling...")
    application.run_polling(drop_pending_updates=True)
