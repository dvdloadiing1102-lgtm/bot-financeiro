import os
import sqlite3
import threading
import logging
import sys
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("ERRO CRÍTICO: Token não configurado no Render!")
    sys.exit()

# --- ESTADOS DO FLUXO (O CÉREBRO DO APP) ---
# Define em que passo o usuário está
(
    SELECT_ACTION,      # Menu Principal
    GASTO_VALOR,        # Esperando valor do gasto
    GASTO_CAT,          # Esperando escolher categoria
    GASTO_DESC,         # Esperando descrição (opcional)
    GANHO_VALOR,        # Esperando valor do ganho
    GANHO_FONTE,        # Esperando fonte do ganho
    NEW_CAT_NAME,       # Esperando nome de nova categoria
    DEL_ID              # Esperando ID para deletar
) = range(8)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- BANCO DE DADOS (COM COMMIT AUTOMÁTICO) ---
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
            conn.commit()

    def get_user_id(self, telegram_id, username):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            res = c.fetchone()
            if res: return res[0]
            c.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username or "Usuario"))
            conn.commit()
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
                cats = ["Alimentacao", "Transporte", "Lazer", "Contas", "Mercado", "Saude", "Outros"]
                for name in cats: c.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))
                conn.commit()
        return uid

    def add_category(self, uid, name):
        with self.db.get_connection() as conn:
            conn.cursor().execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (uid, name))
            conn.commit()

    def delete_category(self, uid, name):
        with self.db.get_connection() as conn:
            conn.cursor().execute("DELETE FROM categories WHERE user_id = ? AND name = ?", (uid, name))
            conn.commit()

    def get_categories(self, uid):
        with self.db.get_connection() as conn:
            rows = conn.cursor().execute("SELECT name FROM categories WHERE user_id = ?", (uid,)).fetchall()
        return [r[0] for r in rows]

    def add_transaction(self, uid, type_, amount, category, desc):
        with self.db.get_connection() as conn:
            conn.cursor().execute("INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)", (uid, type_, amount, category, desc))
            conn.commit()

    def get_detailed_list(self, uid):
        with self.db.get_connection() as conn:
            return conn.cursor().execute("SELECT id, type, amount, category, description, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 15", (uid,)).fetchall()

    def delete_transaction(self, uid, trans_id):
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM transactions WHERE id = ? AND user_id = ?", (trans_id, uid))
            if c.fetchone():
                c.execute("DELETE FROM transactions WHERE id = ?", (trans_id,))
                conn.commit()
                return True
        return False

    def clear_period(self, uid, period):
        with self.db.get_connection() as conn:
            if period == 'all':
                conn.cursor().execute("DELETE FROM transactions WHERE user_id = ?", (uid,))
            elif period == 'month':
                current_month = datetime.now().strftime('%Y-%m')
                conn.cursor().execute("DELETE FROM transactions WHERE user_id = ? AND strftime('%Y-%m', created_at) = ?", (uid, current_month))
            conn.commit()

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
        elements.append(Paragraph("Extrato Financeiro", styles['Heading1']))
        elements.append(Spacer(1, 20))
        data = [["Tipo", "Valor", "Categoria", "Descricao"]]
        for r in rows:
            tipo = "ENTRADA" if r[1] == 'income' else "SAIDA"
            data.append([tipo, f"R$ {r[2]:.2f}", r[3], r[4]])
        t = Table(data)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        elements.append(t)
        doc.build(elements)

bot_logic = FinanceBot()

# --- FUNÇÕES AUXILIARES ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📉 NOVO GASTO", callback_data='start_gasto'), InlineKeyboardButton("📈 NOVO GANHO", callback_data='start_ganho')],
        [InlineKeyboardButton("📊 Saldo", callback_data='view_extrato'), InlineKeyboardButton("📋 Detalhes", callback_data='view_details')],
        [InlineKeyboardButton("📂 Categorias", callback_data='view_cats'), InlineKeyboardButton("🗑️ Lixeira", callback_data='view_lixeira')],
        [InlineKeyboardButton("📄 PDF", callback_data='action_pdf')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- INÍCIO ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_logic.initialize_user(user.id, user.username)
    await update.message.reply_text(
        f"👋 Olá <b>{user.first_name}</b>!\n\nEste é seu App Financeiro. Toque nos botões para começar:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return SELECT_ACTION

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏠 <b>Menu Principal</b>\nO que deseja fazer?",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return SELECT_ACTION

# --- FLUXO 1: ADICIONAR GASTO (WIZARD) ---
async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💸 <b>NOVO GASTO</b>\n\nDigite o valor (ex: 50.00):",
        parse_mode=ParseMode.HTML
    )
    return GASTO_VALOR

async def receive_gasto_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(',', '.')
    try:
        val = float(text)
        context.user_data['temp_valor'] = val
        
        # Gera botões com as categorias do usuário
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        cats = bot_logic.get_categories(uid)
        
        # Cria teclado de categorias (2 por linha)
        keyboard = []
        row = []
        for c in cats:
            row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data='cancel')])
        
        await update.message.reply_text(
            f"Valor: R$ {val:.2f}\nAgora selecione a <b>Categoria</b>:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return GASTO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido! Digite apenas números (ex: 25.50). Tente de novo:")
        return GASTO_VALOR

async def receive_gasto_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'cancel': return await back_to_menu(update, context)
    
    cat_name = data.replace("cat_", "")
    context.user_data['temp_cat'] = cat_name
    
    # Pergunta a descrição com botões rápidos ou digitação
    keyboard = [
        [InlineKeyboardButton("Pular Descrição", callback_data='skip_desc')],
        [InlineKeyboardButton("Ifood", callback_data='desc_Ifood'), InlineKeyboardButton("Uber", callback_data='desc_Uber')],
        [InlineKeyboardButton("Mercado", callback_data='desc_Mercado')]
    ]
    
    await query.edit_message_text(
        f"Categoria: <b>{cat_name}</b>\n\nDigite uma descrição (ex: 'Coxinha') ou escolha abaixo:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return GASTO_DESC

async def receive_gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Pode vir de texto digitado OU de botão
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        if data == 'skip_desc': desc = "Gasto"
        else: desc = data.replace("desc_", "")
        uid = query.from_user.id
        uname = query.from_user.username
        reply_func = query.edit_message_text
    else:
        desc = update.message.text
        uid = update.effective_user.id
        uname = update.effective_user.username
        reply_func = update.message.reply_text

    # SALVAR NO BANCO
    real_uid = bot_logic.initialize_user(uid, uname)
    val = context.user_data['temp_valor']
    cat = context.user_data['temp_cat']
    
    bot_logic.add_transaction(real_uid, "expense", val, cat, desc)
    
    final_msg = f"✅ <b>GASTO SALVO!</b>\n\n💲 Valor: R$ {val:.2f}\n📂 Categoria: {cat}\n📝 Descrição: {desc}"
    
    if update.callback_query:
        await reply_func(final_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Principal", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    else:
        await reply_func(final_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Principal", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    
    return SELECT_ACTION

# --- FLUXO 2: ADICIONAR GANHO ---
async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💰 <b>NOVO GANHO</b>\n\nDigite o valor da entrada (ex: 2000):",
        parse_mode=ParseMode.HTML
    )
    return GANHO_VALOR

async def receive_ganho_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(',', '.')
    try:
        val = float(text)
        context.user_data['temp_valor'] = val
        
        keyboard = [
            [InlineKeyboardButton("Salário", callback_data='src_Salario'), InlineKeyboardButton("Extra", callback_data='src_Extra')],
            [InlineKeyboardButton("Aluguel", callback_data='src_Aluguel'), InlineKeyboardButton("Vendas", callback_data='src_Vendas')],
            [InlineKeyboardButton("Outros", callback_data='src_Outros')]
        ]
        
        await update.message.reply_text(
            f"Valor: R$ {val:.2f}\nDe onde veio esse dinheiro?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return GANHO_FONTE
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return GANHO_VALOR

async def receive_ganho_fonte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        fonte = query.data.replace("src_", "")
        uid = query.from_user.id
        uname = query.from_user.username
        reply_func = query.edit_message_text
    else:
        fonte = update.message.text # Caso o usuário digite manual
        uid = update.effective_user.id
        uname = update.effective_user.username
        reply_func = update.message.reply_text

    real_uid = bot_logic.initialize_user(uid, uname)
    val = context.user_data['temp_valor']
    
    bot_logic.add_transaction(real_uid, "income", val, fonte, "Entrada")
    
    msg = f"✅ <b>GANHO REGISTRADO!</b>\n\n💲 Valor: R$ {val:.2f}\n💰 Fonte: {fonte}"
    
    # Verifica se reply_func é edit_message_text ou reply_text para passar argumentos corretos
    if update.callback_query:
        await reply_func(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Principal", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    else:
        await reply_func(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Principal", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
        
    return SELECT_ACTION

# --- VISUALIZAÇÕES E AÇÕES EXTRAS ---
async def view_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    s = bot_logic.get_summary(uid)
    saldo = s['income'] - s['expense']
    msg = (f"📊 <b>RESUMO FINANCEIRO</b>\n\n"
           f"🟢 Receitas: R$ {s['income']:.2f}\n"
           f"🔴 Despesas: R$ {s['expense']:.2f}\n"
           f"▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
           f"💰 <b>SALDO: R$ {saldo:.2f}</b>")
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def view_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    items = bot_logic.get_detailed_list(uid)
    if not items:
        await query.edit_message_text("📭 Nada registrado ainda.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]))
        return SELECT_ACTION
    
    report = "📋 <b>ÚLTIMOS LANÇAMENTOS:</b>\n\n"
    for item in items:
        icon = "🟢" if item[1] == 'income' else "🔴"
        desc = item[3] # Categoria ou Fonte
        report += f"🆔 <b>{item[0]}</b> | {icon} R$ {item[2]:.2f}\n📌 {desc} ({item[4]})\n"
        report += "----------------\n"
    
    await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def view_lixeira(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("Apagar pelo ID", callback_data='trash_id')],
        [InlineKeyboardButton("Limpar Mês Atual", callback_data='trash_month')],
        [InlineKeyboardButton("ZERAR TUDO", callback_data='trash_all')],
        [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]
    ]
    await query.edit_message_text("🗑️ <b>LIXEIRA</b>\nSelecione uma opção:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def ask_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("🔢 <b>Digite o ID (número) que aparece nos detalhes:</b>", parse_mode=ParseMode.HTML)
    return DEL_ID

async def confirm_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tid = int(update.message.text)
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        if bot_logic.delete_transaction(uid, tid):
            await update.message.reply_text(f"✅ Item {tid} apagado!")
        else:
            await update.message.reply_text("❌ ID não encontrado.")
    except:
        await update.message.reply_text("❌ Erro. Digite apenas o número.")
    
    await update.message.reply_text("🏠 Retornando...", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

# --- CATEGORIAS ---
async def view_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    cats = bot_logic.get_categories(uid)
    msg = "📂 <b>CATEGORIAS ATUAIS:</b>\n\n" + "\n".join([f"• {c}" for c in cats])
    keyboard = [
        [InlineKeyboardButton("➕ Criar Nova", callback_data='new_cat_btn')],
        [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def ask_new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
    return NEW_CAT_NAME

async def save_new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
    bot_logic.add_category(uid, name)
    await update.message.reply_text(f"✅ Categoria <b>{name}</b> criada!", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def action_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    await query.message.reply_text("⏳ Gerando PDF...")
    fname = f"extrato_{uid}.pdf"
    try:
        bot_logic.export_pdf(uid, fname)
        await query.message.reply_document(open(fname, 'rb'))
        os.remove(fname)
    except: await query.message.reply_text("Erro no PDF.")
    return SELECT_ACTION

# --- CANCELAMENTO ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Operação cancelada.", reply_markup=get_main_menu_keyboard())
    return SELECT_ACTION

# --- SERVIDOR ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot APP Mode Online 🚀"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # CONVERSATION HANDLER (A MÁGICA DO APP)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ACTION: [
                CallbackQueryHandler(start_gasto, pattern='^start_gasto$'),
                CallbackQueryHandler(start_ganho, pattern='^start_ganho$'),
                CallbackQueryHandler(view_extrato, pattern='^view_extrato$'),
                CallbackQueryHandler(view_details, pattern='^view_details$'),
                CallbackQueryHandler(view_lixeira, pattern='^view_lixeira$'),
                CallbackQueryHandler(view_cats, pattern='^view_cats$'),
                CallbackQueryHandler(action_pdf, pattern='^action_pdf$'),
                # Submenus da Lixeira
                CallbackQueryHandler(ask_del_id, pattern='^trash_id$'),
                CallbackQueryHandler(back_to_menu, pattern='^main_menu$'),
                # Submenus Cat
                CallbackQueryHandler(ask_new_cat, pattern='^new_cat_btn$'),
            ],
            # Gasto Flow
            GASTO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gasto_valor)],
            GASTO_CAT: [CallbackQueryHandler(receive_gasto_cat)],
            GASTO_DESC: [
                CallbackQueryHandler(receive_gasto_desc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gasto_desc)
            ],
            # Ganho Flow
            GANHO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ganho_valor)],
            GANHO_FONTE: [
                CallbackQueryHandler(receive_ganho_fonte),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ganho_fonte)
            ],
            # Outros States
            NEW_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_cat)],
            DEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_del_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)]
    )
    
    app_bot.add_handler(conv_handler)
    print("Bot APP Mode Iniciado...")
    app_bot.run_polling(drop_pending_updates=True)
