import os
import sqlite3
import threading
import logging
import sys
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURAÇÃO SEGURA ---
# Pega a senha do Cofre do Render (igual você já configurou e funcionou)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    print("ERRO: Token não encontrado no Render! Configure a Environment Variable.")
    sys.exit()

# Configuração de Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- BANCO DE DADOS ---
class FinanceDatabase:
    def __init__(self, db_path="finance_bot.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
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
            c.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username or "Usuario"))
            return c.lastrowid

# --- LÓGICA FINANCEIRA ---
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

# --- INTERFACE COM BOTÕES ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_logic.initialize_user(user.id, user.username)
    
    # Criação dos Botões Flutuantes
    keyboard = [
        [
            InlineKeyboardButton("📊 Ver Extrato", callback_data='btn_extrato'),
            InlineKeyboardButton("📄 Baixar PDF", callback_data='btn_pdf')
        ],
        [
            InlineKeyboardButton("➕ Ajuda Gasto", callback_data='help_gasto'),
            InlineKeyboardButton("💰 Ajuda Ganho", callback_data='help_ganho')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (f"Olá <b>{user.first_name}</b>!\n\n"
           f"Eu sou seu Assistente Financeiro 🤖.\n"
           f"Use os botões abaixo para navegar ou digite os comandos.")
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# --- HANDLER DOS CLIQUES NOS BOTÕES ---
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Avisa o Telegram que o clique foi recebido

    if query.data == 'btn_extrato':
        await extrato(update, context, from_button=True)
    
    elif query.data == 'btn_pdf':
        await pdf(update, context, from_button=True)
    
    elif query.data == 'help_gasto':
        await query.edit_message_text(
            text="🛒 <b>COMO ADICIONAR GASTO:</b>\n\n"
                 "Digite o comando, o valor e o nome:\n"
                 "<code>/gasto 50.00 Padaria</code>\n\n"
                 "Tente digitar agora!",
            parse_mode=ParseMode.HTML
        )
        
    elif query.data == 'help_ganho':
        await query.edit_message_text(
            text="💰 <b>COMO ADICIONAR GANHO:</b>\n\n"
                 "Digite o comando e o valor:\n"
                 "<code>/ganho 1500.00 Salario</code>\n\n"
                 "Tente digitar agora!",
            parse_mode=ParseMode.HTML
        )

# --- COMANDOS ---
async def gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        cat = context.args[1] if len(context.args) > 1 else "Geral"
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "expense", val, cat, "Gasto")
        await update.message.reply_text(f"✅ Gasto de <b>R$ {val:.2f}</b> em <i>{cat}</i> salvo!", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("❌ Erro! Use assim: <code>/gasto 50.00 Mercado</code>", parse_mode=ParseMode.HTML)

async def ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "income", val, "Salario", "Ganho")
        await update.message.reply_text(f"✅ Ganho de <b>R$ {val:.2f}</b> salvo!", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("❌ Erro! Use assim: <code>/ganho 2000.00</code>", parse_mode=ParseMode.HTML)

async def extrato(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False):
    # Lógica para pegar usuário dependendo se veio de botão ou texto
    if from_button:
        user_id = update.callback_query.from_user.id
        username = update.callback_query.from_user.username
        # Para responder ao clique, usamos edit_message ou send_message no context
        func_reply = update.callback_query.message.reply_text
    else:
        user_id = update.effective_user.id
        username = update.effective_user.username
        func_reply = update.message.reply_text

    uid = bot_logic.initialize_user(user_id, username)
    s = bot_logic.get_summary(uid)
    saldo = s['income'] - s['expense']
    cor = "🟢" if saldo >= 0 else "🔴"
    
    msg = (f"📊 <b>RESUMO FINANCEIRO</b>\n\n"
           f"💰 Entradas: R$ {s['income']:.2f}\n"
           f"💸 Saídas:   R$ {s['expense']:.2f}\n"
           f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
           f"{cor} <b>SALDO: R$ {saldo:.2f}</b>")
    
    await func_reply(msg, parse_mode=ParseMode.HTML)

async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False):
    if from_button:
        user_id = update.callback_query.from_user.id
        username = update.callback_query.from_user.username
        message_obj = update.callback_query.message
    else:
        user_id = update.effective_user.id
        username = update.effective_user.username
        message_obj = update.message

    msg = await message_obj.reply_text("⏳ Gerando PDF...")
    uid = bot_logic.initialize_user(user_id, username)
    fname = f"relatorio_{uid}.pdf"
    
    try:
        bot_logic.export_pdf(uid, fname)
        await message_obj.reply_document(open(fname, 'rb'))
        os.remove(fname)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Erro ao gerar PDF: {e}")

# --- INICIALIZAÇÃO ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Financeiro com Botões - ONLINE 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    
    # MODO SEGURO (POLLING)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Registra Comandos e Botões
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gasto", gasto))
    application.add_handler(CommandHandler("ganho", ganho))
    application.add_handler(CommandHandler("extrato", extrato))
    application.add_handler(CommandHandler("pdf", pdf))
    application.add_handler(CallbackQueryHandler(button_click)) # Ouve os cliques

    print("Bot Iniciado...")
    application.run_polling(drop_pending_updates=True)
