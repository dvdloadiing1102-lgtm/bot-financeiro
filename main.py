import os
import sqlite3
import threading
import logging
import sys
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("ERRO: Token não encontrado! Configure no Render.")
    sys.exit()

# Estados para o Bot saber o que você está digitando
WAIT_CAT_NAME, WAIT_DEL_ID, WAIT_DEL_CAT = range(3)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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

# --- LÓGICA DO BOT ---
class FinanceBot:
    def __init__(self, db_path="finance_bot.db"):
        self.db = FinanceDatabase(db_path)

    def initialize_user(self, telegram_id, username):
        uid = self.db.get_user_id(telegram_id, username)
        with self.db.get_connection() as conn:
            c = conn.cursor()
            # Se não tiver categorias, cria as básicas
            c.execute("SELECT id FROM categories WHERE user_id = ?", (uid,))
            if not c.fetchone():
                cats = ["Alimentacao", "Transporte", "Lazer", "Contas", "Mercado"]
                for name in cats: c.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))
        return uid

    def add_category(self, uid, name):
        with self.db.get_connection() as conn:
            conn.cursor().execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))

    def delete_category(self, uid, name):
        with self.db.get_connection() as conn:
            conn.cursor().execute("DELETE FROM categories WHERE user_id = ? AND name = ?", (uid, name))

    def get_categories(self, uid):
        with self.db.get_connection() as conn:
            rows = conn.cursor().execute("SELECT name FROM categories WHERE user_id = ?", (uid,)).fetchall()
        return [r[0] for r in rows]

    def add_transaction(self, uid, type_, amount, category, desc):
        with self.db.get_connection() as conn:
            conn.cursor().execute("INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)", (uid, type_, amount, category, desc))

    def get_detailed_list(self, uid):
        # Retorna lista com ID para poder deletar específico
        with self.db.get_connection() as conn:
            return conn.cursor().execute("SELECT id, type, amount, category, description, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()

    def delete_transaction(self, uid, trans_id):
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM transactions WHERE id = ? AND user_id = ?", (trans_id, uid))
            if c.fetchone():
                c.execute("DELETE FROM transactions WHERE id = ?", (trans_id,))
                return True
        return False

    def clear_period(self, uid, period):
        with self.db.get_connection() as conn:
            if period == 'all':
                conn.cursor().execute("DELETE FROM transactions WHERE user_id = ?", (uid,))
            elif period == 'month':
                # Apaga só do mês atual
                current_month = datetime.now().strftime('%Y-%m')
                conn.cursor().execute("DELETE FROM transactions WHERE user_id = ? AND strftime('%Y-%m', created_at) = ?", (uid, current_month))

    def get_summary(self, uid):
        with self.db.get_connection() as conn:
            rows = conn.cursor().execute("SELECT type, amount, category FROM transactions WHERE user_id = ?", (uid,)).fetchall()
        summary = {"income": 0, "expense": 0}
        for type_, amount, cat in rows:
            if type_ == "income": summary["income"] += amount
            else: summary["expense"] += amount
        return summary

    def export_pdf(self, uid, filename):
        rows = self.get_detailed_list(uid)
        doc = SimpleDocTemplate(filename, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph("Extrato Detalhado", styles['Heading1']))
        elements.append(Spacer(1, 20))
        
        data = [["ID", "Tipo", "Valor", "Categoria", "Descrição"]]
        for r in rows:
            tipo = "Ganho" if r[1] == 'income' else "Gasto"
            data.append([str(r[0]), tipo, f"R$ {r[2]:.2f}", r[3], r[4]])

        t = Table(data)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        elements.append(t)
        doc.build(elements)

bot_logic = FinanceBot()

# --- FUNÇÕES DE MENU ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_logic.initialize_user(user.id, user.username)
    await show_main_menu(update)

async def show_main_menu(update):
    keyboard = [
        [InlineKeyboardButton("🔍 Análise Detalhada", callback_data='menu_analise')],
        [InlineKeyboardButton("📂 Categorias", callback_data='menu_cats'), InlineKeyboardButton("🗑️ Lixeira", callback_data='menu_lixeira')],
        [InlineKeyboardButton("📊 Saldo Rápido", callback_data='btn_extrato'), InlineKeyboardButton("📄 PDF", callback_data='btn_pdf')],
        [InlineKeyboardButton("❓ Ajuda", callback_data='btn_help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg_text = "🤖 <b>PAINEL FINANCEIRO PRO</b>\n\nEscolha uma opção abaixo:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# --- ANÁLISE DETALHADA ---
async def detailed_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    items = bot_logic.get_detailed_list(uid)

    if not items:
        await query.edit_message_text("📭 Nenhuma transação encontrada.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]))
        return

    report = "📋 <b>ÚLTIMAS TRANSAÇÕES:</b>\n\n"
    for item in items:
        # item: id, type, amount, cat, desc, date
        icon = "🟢" if item[1] == 'income' else "🔴"
        report += f"🆔 <b>{item[0]}</b> | {icon} R$ {item[2]:.2f}\n"
        report += f"📝 <i>{item[4]}</i> ({item[3]})\n"
        report += "-----------------------------\n"
    
    report += "\n💡 <i>Para apagar um item específico, vá na Lixeira e use o ID (número em negrito).</i>"
    
    keyboard = [[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]
    await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# --- GESTÃO DE CATEGORIAS ---
async def menu_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    cats = bot_logic.get_categories(uid)
    
    cat_text = "📂 <b>SUAS CATEGORIAS:</b>\n\n" + "\n".join([f"• {c}" for c in cats])
    
    keyboard = [
        [InlineKeyboardButton("➕ Adicionar Categoria", callback_data='add_cat')],
        [InlineKeyboardButton("➖ Deletar Categoria", callback_data='del_cat')],
        [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]
    ]
    await query.edit_message_text(cat_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def prompt_add_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
    return WAIT_CAT_NAME

async def save_new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    bot_logic.add_category(uid, text)
    await update.message.reply_text(f"✅ Categoria <b>{text}</b> adicionada!", parse_mode=ParseMode.HTML)
    await show_main_menu(update)
    return ConversationHandler.END

async def prompt_del_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("✍️ <b>Digite o nome da categoria para EXCLUIR:</b>", parse_mode=ParseMode.HTML)
    return WAIT_DEL_CAT

async def delete_existing_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    bot_logic.delete_category(uid, text)
    await update.message.reply_text(f"✅ Categoria <b>{text}</b> removida (se existia).", parse_mode=ParseMode.HTML)
    await show_main_menu(update)
    return ConversationHandler.END

# --- LIXEIRA (DELETAR TUDO OU ESPECÍFICO) ---
async def menu_lixeira(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🗑️ Apagar item pelo ID", callback_data='del_id')],
        [InlineKeyboardButton("📅 Apagar Este Mês", callback_data='del_month')],
        [InlineKeyboardButton("🔥 ZERAR TUDO", callback_data='del_all')],
        [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]
    ]
    await update.callback_query.edit_message_text("🗑️ <b>GERENCIAR EXCLUSÃO</b>\n\nO que você deseja apagar?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def prompt_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("🔢 <b>Digite o ID (número) da transação que quer apagar:</b>\n(Veja o ID na Análise Detalhada)", parse_mode=ParseMode.HTML)
    return WAIT_DEL_ID

async def execute_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tid = int(update.message.text)
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        if bot_logic.delete_transaction(uid, tid):
            await update.message.reply_text(f"✅ Transação <b>ID {tid}</b> apagada!", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ ID não encontrado ou não pertence a você.")
    except:
        await update.message.reply_text("❌ Erro: Digite apenas o número.")
    
    await show_main_menu(update)
    return ConversationHandler.END

async def execute_del_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    
    if query.data == 'del_month':
        bot_logic.clear_period(uid, 'month')
        msg = "✅ Dados deste mês foram apagados."
    elif query.data == 'del_all':
        bot_logic.clear_period(uid, 'all')
        msg = "🔥 <b>TODOS OS DADOS FORAM APAGADOS.</b> Conta zerada."
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)

# --- COMANDOS E EXTRATOS ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "ℹ️ <b>COMO USAR:</b>\n\n"
            "🛒 <b>Adicionar Gasto:</b>\n"
            "<code>/gasto 30.00 Ifood</code>\n\n"
            "💰 <b>Adicionar Salário/Ganho:</b>\n"
            "<code>/ganho 2500.00 Salario</code>\n\n"
            "📂 <b>Categorias:</b> Use o menu para criar novas.\n"
            "🗑️ <b>Apagar:</b> Vá em 'Lixeira' para apagar itens específicos.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]),
            parse_mode=ParseMode.HTML
        )

async def gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        desc = " ".join(context.args[1:]) if len(context.args) > 1 else "Gasto"
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        # Tenta adivinhar categoria ou usa "Geral"
        cat = "Alimentacao" if "ifood" in desc.lower() or "mercado" in desc.lower() else "Geral"
        bot_logic.add_transaction(uid, "expense", val, cat, desc)
        await update.message.reply_text(f"📉 Gasto de <b>R$ {val:.2f}</b> ({desc}) salvo!", parse_mode=ParseMode.HTML)
    except: await update.message.reply_text("❌ Use: <code>/gasto 30.00 Ifood</code>", parse_mode=ParseMode.HTML)

async def ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0].replace(',', '.'))
        desc = " ".join(context.args[1:]) if len(context.args) > 1 else "Salario"
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        bot_logic.add_transaction(uid, "income", val, "Salario", desc)
        await update.message.reply_text(f"📈 Ganho de <b>R$ {val:.2f}</b> salvo!", parse_mode=ParseMode.HTML)
    except: await update.message.reply_text("❌ Use: <code>/ganho 2000.00</code>", parse_mode=ParseMode.HTML)

async def simple_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        uid = bot_logic.initialize_user(update.callback_query.from_user.id, update.callback_query.from_user.username)
        reply = update.callback_query.edit_message_text
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]])
    else:
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        reply = update.message.reply_text
        markup = None
        
    s = bot_logic.get_summary(uid)
    msg = (f"📊 <b>RESUMO RÁPIDO</b>\n\n🟢 Entrou: R$ {s['income']:.2f}\n🔴 Saiu: R$ {s['expense']:.2f}\n➖➖➖➖➖➖\n💰 <b>SALDO: R$ {s['income'] - s['expense']:.2f}</b>")
    await reply(msg, reply_markup=markup, parse_mode=ParseMode.HTML)

async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    await query.message.reply_text("⏳ Gerando PDF...")
    fname = f"extrato_{uid}.pdf"
    try:
        bot_logic.export_pdf(uid, fname)
        await query.message.reply_document(open(fname, 'rb'))
        os.remove(fname)
    except Exception as e: await query.message.reply_text(f"Erro: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Ação cancelada.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data='main_menu')]]))
    return ConversationHandler.END

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Financeiro MASTER Online 🚀"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers de Conversa (Para quando o bot pergunta e você responde)
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(prompt_add_cat, pattern='^add_cat$'),
            CallbackQueryHandler(prompt_del_cat, pattern='^del_cat$'),
            CallbackQueryHandler(prompt_del_id, pattern='^del_id$'),
        ],
        states={
            WAIT_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_cat)],
            WAIT_DEL_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_existing_cat)],
            WAIT_DEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_del_id)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app_bot.add_handler(conv_handler)
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("gasto", gasto))
    app_bot.add_handler(CommandHandler("ganho", ganho))
    app_bot.add_handler(CommandHandler("extrato", simple_extrato))
    
    # Menu Navigation
    app_bot.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    app_bot.add_handler(CallbackQueryHandler(detailed_analysis, pattern='^menu_analise$'))
    app_bot.add_handler(CallbackQueryHandler(menu_cats, pattern='^menu_cats$'))
    app_bot.add_handler(CallbackQueryHandler(menu_lixeira, pattern='^menu_lixeira$'))
    app_bot.add_handler(CallbackQueryHandler(simple_extrato, pattern='^btn_extrato$'))
    app_bot.add_handler(CallbackQueryHandler(pdf, pattern='^btn_pdf$'))
    app_bot.add_handler(CallbackQueryHandler(help_cmd, pattern='^btn_help$'))
    app_bot.add_handler(CallbackQueryHandler(execute_del_period, pattern='^del_month$|^del_all$'))

    print("Bot Master Iniciado...")
    app_bot.run_polling(drop_pending_updates=True)
