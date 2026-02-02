import os
import sqlite3
import threading
import logging
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import csv
import requests
import time
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
    print("ERRO CRÍTICO: Token não configurado!")
    sys.exit()

# Estados do Fluxo
(SELECT_ACTION, GASTO_VALOR, GASTO_CAT, GASTO_DESC, GANHO_VALOR, GANHO_CAT, NEW_CAT_NAME, NEW_CAT_TYPE, DEL_ID, CONFIRM_DEL_CAT) = range(10)

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
            c.execute("""CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, cat_type TEXT DEFAULT 'expense')""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT, amount REAL, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            try:
                c.execute("SELECT cat_type FROM categories LIMIT 1")
            except:
                c.execute("ALTER TABLE categories ADD COLUMN cat_type TEXT DEFAULT 'expense'")
                conn.commit()
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
                cats_exp = ["Alimentacao", "Transporte", "Lazer", "Contas", "Mercado"]
                for name in cats_exp: c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, 'expense')", (uid, name))
                cats_inc = ["Salario", "Extra", "Vendas"]
                for name in cats_inc: c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, 'income')", (uid, name))
                conn.commit()
        return uid

    def add_category(self, uid, name, cat_type):
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM categories WHERE user_id = ? AND name = ? AND cat_type = ?", (uid, name, cat_type))
            if not c.fetchone():
                c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, ?)", (uid, name, cat_type))
                conn.commit()

    def delete_category(self, uid, name, cat_type):
        with self.db.get_connection() as conn:
            # Deleta apenas a categoria da lista de opções
            # (Mantém os gastos históricos para não quebrar relatórios)
            conn.cursor().execute("DELETE FROM categories WHERE user_id = ? AND name = ? AND cat_type = ?", (uid, name, cat_type))
            conn.commit()

    def get_categories(self, uid, cat_type=None):
        with self.db.get_connection() as conn:
            if cat_type:
                rows = conn.cursor().execute("SELECT name FROM categories WHERE user_id = ? AND cat_type = ?", (uid, cat_type)).fetchall()
            else:
                rows = conn.cursor().execute("SELECT name, cat_type FROM categories WHERE user_id = ?", (uid,)).fetchall()
                return rows # Retorna tuplas (nome, tipo)
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

    def get_summary(self, uid):
        with self.db.get_connection() as conn:
            rows = conn.cursor().execute("SELECT type, amount, category FROM transactions WHERE user_id = ?", (uid,)).fetchall()
        summary = {"income": 0, "expense": 0, "cats": {}}
        for type_, amount, cat in rows:
            if type_ == "income": summary["income"] += amount
            else: 
                summary["expense"] += amount
                if cat not in summary["cats"]: summary["cats"][cat] = 0
                summary["cats"][cat] += amount
        return summary

    def generate_chart(self, uid):
        summary = self.get_summary(uid)
        cats = summary['cats']
        if not cats: return None
        total = sum(cats.values())
        filtered_cats = {k: v for k, v in cats.items() if v/total > 0.01} 
        labels = list(filtered_cats.keys())
        sizes = list(filtered_cats.values())
        plt.figure(figsize=(6, 6))
        plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140)
        plt.title('Distribuição de Gastos')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        return buf

    def export_csv(self, uid):
        rows = self.get_detailed_list(uid) # Pega tudo
        # Mas vamos pegar TUDO mesmo do banco para o Excel
        with self.db.get_connection() as conn:
            all_rows = conn.cursor().execute("SELECT type, amount, category, description, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Tipo', 'Valor', 'Categoria', 'Descricao', 'Data']) # Cabeçalho
        
        for r in all_rows:
            tipo = "Entrada" if r[0] == 'income' else "Saida"
            writer.writerow([tipo, r[1], r[2], r[3], r[4]])
            
        return output.getvalue()

    def export_pdf(self, uid, filename):
        rows = self.get_detailed_list(uid)
        doc = SimpleDocTemplate(filename, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph("Extrato Financeiro Completo", styles['Heading1']))
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

# --- MENUS ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📉 NOVO GASTO", callback_data='start_gasto'), InlineKeyboardButton("📈 NOVO GANHO", callback_data='start_ganho')],
        [InlineKeyboardButton("📊 Saldo", callback_data='view_extrato'), InlineKeyboardButton("🍕 Gráfico", callback_data='view_chart')],
        [InlineKeyboardButton("📂 Categorias (Editar)", callback_data='view_cats'), InlineKeyboardButton("📋 Detalhes", callback_data='view_details')],
        [InlineKeyboardButton("📄 PDF", callback_data='action_pdf'), InlineKeyboardButton("📊 Excel (CSV)", callback_data='action_csv')],
        [InlineKeyboardButton("🗑️ Lixeira", callback_data='view_lixeira')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- INÍCIO ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_logic.initialize_user(user.id, user.username)
    await update.message.reply_text(
        f"👋 Olá <b>{user.first_name}</b>!\n\nSeu App Financeiro PRO está ONLINE 🟢\nControle total nas suas mãos:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return SELECT_ACTION

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏠 <b>Menu Principal</b>", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

# --- FLUXO GASTO ---
async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💸 <b>NOVO GASTO</b>\n\nDigite o valor (ex: 50.00):", parse_mode=ParseMode.HTML)
    return GASTO_VALOR

async def receive_gasto_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(',', '.')
    try:
        val = float(text)
        context.user_data['temp_valor'] = val
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        cats = bot_logic.get_categories(uid, 'expense')
        
        keyboard = []
        row = []
        for c in cats:
            row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("➕ Criar Categoria", callback_data='create_new_cat_flow')])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data='cancel')])
        
        await update.message.reply_text(f"Valor: R$ {val:.2f}\n<b>Selecione a Categoria de Gasto:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return GASTO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return GASTO_VALOR

async def receive_gasto_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'cancel': return await back_to_menu(update, context)
    if data == 'create_new_cat_flow':
        await query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    
    context.user_data['temp_cat'] = data.replace("cat_", "")
    keyboard = [[InlineKeyboardButton("Pular Descrição", callback_data='skip_desc')]]
    await query.edit_message_text("📝 Digite uma descrição (ex: 'Lanche') ou Pule:", reply_markup=InlineKeyboardMarkup(keyboard))
    return GASTO_DESC

async def receive_gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        desc = "Gasto"
        reply_func = update.callback_query.edit_message_text
        uid = update.callback_query.from_user.id
        uname = update.callback_query.from_user.username
    else:
        desc = update.message.text
        reply_func = update.message.reply_text
        uid = update.effective_user.id
        uname = update.effective_user.username

    real_uid = bot_logic.initialize_user(uid, uname)
    bot_logic.add_transaction(real_uid, "expense", context.user_data['temp_valor'], context.user_data['temp_cat'], desc)
    await reply_func("✅ <b>Gasto Salvo!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

# --- FLUXO GANHO ---
async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💰 <b>NOVO GANHO</b>\n\nDigite o valor (ex: 2000):", parse_mode=ParseMode.HTML)
    return GANHO_VALOR

async def receive_ganho_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(',', '.')
    try:
        val = float(text)
        context.user_data['temp_valor'] = val
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        cats = bot_logic.get_categories(uid, 'income')
        
        keyboard = []
        row = []
        for c in cats:
            row.append(InlineKeyboardButton(c, callback_data=f"inc_{c}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("➕ Criar Categoria", callback_data='create_new_cat_flow')])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data='cancel')])

        await update.message.reply_text("Escolha a Fonte/Categoria:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GANHO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return GANHO_VALOR

async def receive_ganho_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'cancel': return await back_to_menu(update, context)
    if data == 'create_new_cat_flow':
        await query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME

    fonte = data.replace("inc_", "")
    uid = query.from_user.id
    uname = query.from_user.username
    real_uid = bot_logic.initialize_user(uid, uname)
    bot_logic.add_transaction(real_uid, "income", context.user_data['temp_valor'], fonte, "Entrada")
    
    await query.edit_message_text("✅ <b>Ganho Salvo!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

# --- NOVA CATEGORIA ---
async def save_new_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_cat_name'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("💸 É um Gasto", callback_data='type_expense')],
        [InlineKeyboardButton("💰 É um Ganho", callback_data='type_income')]
    ]
    await update.message.reply_text(f"A categoria <b>{update.message.text}</b> é de:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return NEW_CAT_TYPE

async def save_new_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_type = query.data.replace("type_", "")
    name = context.user_data['new_cat_name']
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    bot_logic.add_category(uid, name, cat_type)
    await query.edit_message_text(f"✅ Categoria <b>{name}</b> criada!", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

# --- GERENCIADOR DE CATEGORIAS (VIEW & DELETE) ---
async def view_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    
    # Busca todas as categorias
    all_cats = bot_logic.get_categories(uid) # Retorna lista de tuplas (nome, tipo)
    
    if not all_cats:
        await query.edit_message_text("📂 Nenhuma categoria encontrada.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]))
        return SELECT_ACTION

    keyboard = []
    # Cria botões com ícone de lixeira
    for name, cat_type in all_cats:
        icon = "📉" if cat_type == 'expense' else "📈"
        # Callback data envia: delcat_TIPO_NOME
        callback = f"delcat_{cat_type}_{name}"
        keyboard.append([InlineKeyboardButton(f"{icon} {name} (❌ Apagar)", callback_data=callback)])
    
    keyboard.append([InlineKeyboardButton("➕ Criar Nova", callback_data='new_cat_btn')])
    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')])
    
    await query.edit_message_text("📂 <b>GERENCIAR CATEGORIAS</b>\nClique para apagar:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return CONFIRM_DEL_CAT

async def delete_cat_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'new_cat_btn':
        await query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    if data == 'main_menu':
        return await back_to_menu(update, context)

    # Processa deleção: data = delcat_expense_NomeDaCat
    try:
        _, cat_type, cat_name = data.split('_', 2)
        uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
        bot_logic.delete_category(uid, cat_name, cat_type)
        
        # Atualiza a lista removendo o botão
        await view_cats(update, context)
    except:
        await query.edit_message_text("❌ Erro ao apagar.", reply_markup=get_main_menu_keyboard())
    
    return CONFIRM_DEL_CAT

# --- VISUALIZAÇÕES E AÇÕES ---
async def view_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    items = bot_logic.get_detailed_list(uid)
    if not items:
        await query.edit_message_text("📭 Nada registrado ainda.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]))
    else:
        report = "📋 <b>ÚLTIMOS LANÇAMENTOS:</b>\n\n"
        for item in items:
            icon = "🟢" if item[1] == 'income' else "🔴"
            report += f"🆔 <b>{item[0]}</b> | {icon} R$ {item[2]:.2f}\n📌 {item[3]} ({item[4]})\n----------------\n"
        await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def view_lixeira(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [[InlineKeyboardButton("Apagar pelo ID", callback_data='trash_id')], [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]
    await query.edit_message_text("🗑️ <b>LIXEIRA</b>\nPara apagar, veja o número ID no menu 'Detalhes'.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def ask_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("🔢 <b>Digite o ID (número) que quer apagar:</b>", parse_mode=ParseMode.HTML)
    return DEL_ID

async def confirm_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tid = int(update.message.text)
        uid = bot_logic.initialize_user(update.effective_user.id, update.effective_user.username)
        if bot_logic.delete_transaction(uid, tid): await update.message.reply_text(f"✅ Item {tid} apagado!")
        else: await update.message.reply_text("❌ ID não encontrado.")
    except: await update.message.reply_text("❌ Erro no número.")
    await update.message.reply_text("🏠 Menu", reply_markup=get_main_menu_keyboard())
    return SELECT_ACTION

async def view_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    await query.message.reply_text("🎨 Gerando gráfico...")
    chart_buf = bot_logic.generate_chart(uid)
    if chart_buf:
        await query.message.reply_photo(photo=chart_buf, caption="📊 Seus gastos por categoria")
    else:
        await query.message.reply_text("❌ Sem dados suficientes para gráfico.")
    await query.message.reply_text("🏠 Menu", reply_markup=get_main_menu_keyboard())
    return SELECT_ACTION

async def view_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    s = bot_logic.get_summary(uid)
    msg = f"📊 <b>RESUMO</b>\n\n🟢 Receitas: R$ {s['income']:.2f}\n🔴 Despesas: R$ {s['expense']:.2f}\n💰 <b>Saldo: R$ {s['income']-s['expense']:.2f}</b>"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def action_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    await query.message.reply_text("⏳ Gerando PDF...")
    try:
        fname = f"extrato_{uid}.pdf"
        bot_logic.export_pdf(uid, fname)
        await query.message.reply_document(open(fname, 'rb'))
        os.remove(fname)
    except: await query.message.reply_text("Erro no PDF.")
    return SELECT_ACTION

async def action_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = bot_logic.initialize_user(query.from_user.id, query.from_user.username)
    await query.message.reply_text("⏳ Gerando Planilha Excel (CSV)...")
    try:
        csv_data = bot_logic.export_csv(uid)
        # Envia como arquivo
        await query.message.reply_document(document=io.BytesIO(csv_data.encode()), filename="planilha_financeira.csv")
    except Exception as e:
        await query.message.reply_text(f"Erro no CSV: {e}")
    return SELECT_ACTION

async def start_new_cat_flow_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
    return NEW_CAT_NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Cancelado.", reply_markup=get_main_menu_keyboard())
    return SELECT_ACTION

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Financeiro - ONLINE 🟢"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive_ping():
    while True:
        try: requests.get("http://127.0.0.1:10000")
        except: pass
        time.sleep(600)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ACTION: [
                CallbackQueryHandler(start_gasto, pattern='^start_gasto$'),
                CallbackQueryHandler(start_ganho, pattern='^start_ganho$'),
                CallbackQueryHandler(view_extrato, pattern='^view_extrato$'),
                CallbackQueryHandler(view_chart, pattern='^view_chart$'),
                CallbackQueryHandler(view_cats, pattern='^view_cats$'),
                CallbackQueryHandler(view_details, pattern='^view_details$'),
                CallbackQueryHandler(view_lixeira, pattern='^view_lixeira$'),
                CallbackQueryHandler(action_pdf, pattern='^action_pdf$'),
                CallbackQueryHandler(action_csv, pattern='^action_csv$'),
                CallbackQueryHandler(ask_del_id, pattern='^trash_id$'),
                CallbackQueryHandler(start_new_cat_flow_from_menu, pattern='^new_cat_btn$'),
                CallbackQueryHandler(back_to_menu, pattern='^main_menu$')
            ],
            GASTO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gasto_valor)],
            GASTO_CAT: [CallbackQueryHandler(receive_gasto_cat)],
            GASTO_DESC: [CallbackQueryHandler(receive_gasto_desc), MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gasto_desc)],
            GANHO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ganho_valor)],
            GANHO_CAT: [CallbackQueryHandler(receive_ganho_cat)],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_cat_name)],
            NEW_CAT_TYPE: [CallbackQueryHandler(save_new_cat_type)],
            DEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_del_id)],
            CONFIRM_DEL_CAT: [CallbackQueryHandler(delete_cat_confirm)], # Novo estado para deletar categoria
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)]
    )
    
    app_bot.add_handler(conv_handler)
    print("Bot Iniciado...")
    app_bot.run_polling(drop_pending_updates=True)
