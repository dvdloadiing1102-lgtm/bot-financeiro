import os
import sqlite3
import threading
import logging
import sys
import matplotlib
matplotlib.use('Agg') # Essencial para o Render
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
    print("AVISO: Token não configurado.")

# Estados do Fluxo
(SELECT_ACTION, GASTO_VALOR, GASTO_CAT, GASTO_DESC, GANHO_VALOR, GANHO_CAT, 
 NEW_CAT_NAME, NEW_CAT_TYPE, DEL_ID, CONFIRM_DEL_CAT, SET_GOAL_VAL, DELETE_HUB) = range(12)

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
            c.execute("""CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, cat_type TEXT DEFAULT 'expense', goal_limit REAL DEFAULT 0)""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT, amount REAL, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            try: c.execute("ALTER TABLE categories ADD COLUMN goal_limit REAL DEFAULT 0")
            except: pass
            try: c.execute("ALTER TABLE categories ADD COLUMN cat_type TEXT DEFAULT 'expense'")
            except: pass
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

bot_db = FinanceDatabase()

# --- LÓGICA DE NEGÓCIO ---
def initialize_user(telegram_id, username):
    uid = bot_db.get_user_id(telegram_id, username)
    with bot_db.get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM categories WHERE user_id = ?", (uid,))
        if not c.fetchone():
            cats_exp = ["Alimentacao", "Transporte", "Lazer", "Contas", "Mercado"]
            for name in cats_exp: c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, 'expense')", (uid, name))
            cats_inc = ["Salario", "Extra", "Vendas"]
            for name in cats_inc: c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, 'income')", (uid, name))
            conn.commit()
    return uid

def get_categories(uid, cat_type=None):
    with bot_db.get_connection() as conn:
        if cat_type:
            rows = conn.cursor().execute("SELECT name FROM categories WHERE user_id = ? AND cat_type = ?", (uid, cat_type)).fetchall()
        else:
            rows = conn.cursor().execute("SELECT name, cat_type, goal_limit FROM categories WHERE user_id = ?", (uid,)).fetchall()
            return rows
    return [r[0] for r in rows]

def check_goal(uid, cat_name, added_amount):
    with bot_db.get_connection() as conn:
        c = conn.cursor()
        res = c.execute("SELECT goal_limit FROM categories WHERE user_id = ? AND name = ?", (uid, cat_name)).fetchone()
        if not res or res[0] <= 0: return None
        limit = res[0]
        month = datetime.now().strftime('%Y-%m')
        spent = c.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND category = ? AND type = 'expense' AND strftime('%Y-%m', created_at) = ?", (uid, cat_name, month)).fetchone()[0] or 0
        total = spent + added_amount
        if total > limit: return f"⚠️ <b>ALERTA:</b> Meta estourada em {cat_name}!"
        return None

def add_transaction(uid, type_, amount, category, desc):
    with bot_db.get_connection() as conn:
        conn.cursor().execute("INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)", (uid, type_, amount, category, desc))
        conn.commit()

def add_category(uid, name, cat_type):
    with bot_db.get_connection() as conn:
        conn.cursor().execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, ?)", (uid, name, cat_type))
        conn.commit()

def delete_category(uid, name, cat_type):
    with bot_db.get_connection() as conn:
        conn.cursor().execute("DELETE FROM categories WHERE user_id = ? AND name = ? AND cat_type = ?", (uid, name, cat_type))
        conn.commit()

def set_goal(uid, cat_name, limit):
    with bot_db.get_connection() as conn:
        conn.cursor().execute("UPDATE categories SET goal_limit = ? WHERE user_id = ? AND name = ?", (limit, uid, cat_name))
        conn.commit()

def get_detailed_list(uid):
    with bot_db.get_connection() as conn:
        return conn.cursor().execute("SELECT id, type, amount, category, description, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 15", (uid,)).fetchall()

def delete_transaction(uid, trans_id):
    with bot_db.get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM transactions WHERE id = ? AND user_id = ?", (trans_id, uid))
        if c.fetchone():
            c.execute("DELETE FROM transactions WHERE id = ?", (trans_id,))
            conn.commit()
            return True
    return False

def get_summary(uid):
    with bot_db.get_connection() as conn:
        rows = conn.cursor().execute("SELECT type, amount, category FROM transactions WHERE user_id = ?", (uid,)).fetchall()
    summary = {"income": 0, "expense": 0, "cats": {}}
    for type_, amount, cat in rows:
        if type_ == "income": summary["income"] += amount
        else: 
            summary["expense"] += amount
            if cat not in summary["cats"]: summary["cats"][cat] = 0
            summary["cats"][cat] += amount
    return summary

def generate_chart(uid):
    summary = get_summary(uid)
    cats = summary['cats']
    if not cats: return None
    labels = list(cats.keys())
    sizes = list(cats.values())
    plt.figure(figsize=(6, 6))
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140)
    plt.title('Gastos')
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

def export_csv(uid):
    with bot_db.get_connection() as conn:
        all_rows = conn.cursor().execute("SELECT type, amount, category, description, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tipo', 'Valor', 'Categoria', 'Descricao', 'Data'])
    for r in all_rows:
        writer.writerow(["Entrada" if r[0] == 'income' else "Saida", r[1], r[2], r[3], r[4]])
    return output.getvalue()

def export_pdf(uid, filename):
    rows = get_detailed_list(uid)
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

# --- MENUS (LAYOUT ANTIGO - CLASSICO) ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📉 NOVO GASTO", callback_data='start_gasto'), InlineKeyboardButton("📈 NOVO GANHO", callback_data='start_ganho')],
        [InlineKeyboardButton("📊 Saldo", callback_data='view_extrato'), InlineKeyboardButton("🍕 Gráfico", callback_data='view_chart')],
        [InlineKeyboardButton("📂 Categorias", callback_data='view_cats'), InlineKeyboardButton("🗑️ Central de Exclusão", callback_data='start_delete_hub')],
        [InlineKeyboardButton("📦 Backup", callback_data='backup_db'), InlineKeyboardButton("📄 PDF/Excel", callback_data='action_files')],
        [InlineKeyboardButton("📋 Detalhes Recentes", callback_data='view_details')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- HANDLERS (DEFINIDOS NA ORDEM CORRETA) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    initialize_user(user.id, user.username)
    await update.message.reply_text(f"👋 Olá <b>{user.first_name}</b>!\n\nBot Financeiro ONLINE 🟢\nEscolha uma opção:", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏠 <b>Menu Principal</b>", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

# Helper importante: definido antes de ser chamado
async def start_new_cat_flow_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
    return NEW_CAT_NAME

async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("📉 <b>NOVO GASTO</b>\nDigite o valor (ex: 20.00):", parse_mode=ParseMode.HTML)
    return GASTO_VALOR

async def receive_gasto_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(',', '.'))
        context.user_data['temp_valor'] = val
        uid = initialize_user(update.effective_user.id, update.effective_user.username)
        cats = get_categories(uid, 'expense')
        keyboard = []
        row = []
        for c in cats:
            row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
            if len(row) == 2: keyboard.append(row); row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("➕ Criar Categoria", callback_data='create_new_cat_flow')])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data='cancel')])
        await update.message.reply_text(f"Valor: R$ {val:.2f}\n<b>Escolha a Categoria:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return GASTO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return GASTO_VALOR

async def receive_gasto_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    if data == 'cancel': return await back_to_menu(update, context)
    if data == 'create_new_cat_flow':
        await query.edit_message_text("✍️ <b>Nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    context.user_data['temp_cat'] = data.replace("cat_", "")
    await query.edit_message_text("📝 Digite a descrição (ou pule):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Pular", callback_data='skip_desc')]]))
    return GASTO_DESC

async def receive_gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        desc = "Gasto"; uid = update.callback_query.from_user.id; uname = update.callback_query.from_user.username; reply_func = update.callback_query.edit_message_text
    else:
        desc = update.message.text; uid = update.effective_user.id; uname = update.effective_user.username; reply_func = update.message.reply_text
    real_uid = initialize_user(uid, uname)
    val = context.user_data['temp_valor']
    cat = context.user_data['temp_cat']
    alert = check_goal(real_uid, cat, val)
    add_transaction(real_uid, "expense", val, cat, desc)
    msg = f"✅ <b>Gasto Salvo!</b>\nR$ {val:.2f} em {cat}."
    if alert: msg += f"\n\n{alert}"
    kb = [[InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]
    await reply_func(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("📈 <b>NOVO GANHO</b>\nDigite o valor:", parse_mode=ParseMode.HTML)
    return GANHO_VALOR

async def receive_ganho_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(',', '.'))
        context.user_data['temp_valor'] = val
        uid = initialize_user(update.effective_user.id, update.effective_user.username)
        cats = get_categories(uid, 'income')
        keyboard = []
        for c in cats: keyboard.append([InlineKeyboardButton(c, callback_data=f"inc_{c}")])
        keyboard.append([InlineKeyboardButton("➕ Criar Categoria", callback_data='create_new_cat_flow')])
        await update.message.reply_text("Fonte:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GANHO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return GANHO_VALOR

async def receive_ganho_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'create_new_cat_flow':
        await query.edit_message_text("✍️ <b>Nome da categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    fonte = query.data.replace("inc_", "")
    add_transaction(initialize_user(query.from_user.id, query.from_user.username), "income", context.user_data['temp_valor'], fonte, "Entrada")
    await query.edit_message_text("✅ <b>Ganho Salvo!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def save_new_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_cat_name'] = update.message.text
    kb = [[InlineKeyboardButton("Gasto", callback_data='type_expense'), InlineKeyboardButton("Ganho", callback_data='type_income')]]
    await update.message.reply_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def save_new_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cat_type = query.data.replace("type_", "")
    uid = initialize_user(query.from_user.id, query.from_user.username)
    add_category(uid, context.user_data['new_cat_name'], cat_type)
    await query.edit_message_text(f"✅ Categoria <b>{context.user_data['new_cat_name']}</b> criada!", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def view_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = initialize_user(query.from_user.id, query.from_user.username)
    cats = get_categories(uid)
    keyboard = []
    for name, ctype, goal in cats:
        icon = "📉" if ctype == 'expense' else "📈"
        goal_txt = f" (Meta: {goal})" if goal > 0 else ""
        keyboard.append([InlineKeyboardButton(f"{icon} {name}{goal_txt}", callback_data=f"opt_{ctype}_{name}")])
    keyboard.append([InlineKeyboardButton("➕ Criar Nova", callback_data='new_cat_btn')])
    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')])
    await query.edit_message_text("📂 <b>GERENCIAR CATEGORIAS</b>\nClique para editar:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return CONFIRM_DEL_CAT

async def cat_options_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    if data == 'new_cat_btn':
        await query.edit_message_text("✍️ <b>Digite o nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    if data == 'main_menu': return await back_to_menu(update, context)
    if data.startswith('opt_'):
        _, ctype, cname = data.split("_", 2)
        context.user_data['target_cat'] = (cname, ctype)
        kb = [[InlineKeyboardButton("🎯 Definir Meta", callback_data='set_goal')],
              [InlineKeyboardButton("🗑️ Apagar Categoria", callback_data='del_cat_confirm')],
              [InlineKeyboardButton("🔙 Voltar", callback_data='back_cats')]]
        await query.edit_message_text(f"Opções para <b>{cname}</b>:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        return CONFIRM_DEL_CAT
    if data == 'back_cats': return await view_cats(update, context)
    if data == 'del_cat_confirm':
        cname, ctype = context.user_data['target_cat']
        delete_category(initialize_user(query.from_user.id, query.from_user.username), cname, ctype)
        await query.edit_message_text(f"🗑️ {cname} apagada.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Voltar", callback_data='back_cats')]]))
        return CONFIRM_DEL_CAT
    if data == 'set_goal':
        cname, _ = context.user_data['target_cat']
        await query.edit_message_text(f"🎯 Meta mensal para <b>{cname}</b>:", parse_mode=ParseMode.HTML)
        return SET_GOAL_VAL

async def save_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(',', '.'))
        cname, _ = context.user_data['target_cat']
        set_goal(initialize_user(update.effective_user.id, update.effective_user.username), cname, val)
        await update.message.reply_text("✅ Meta salva!", reply_markup=get_main_menu_keyboard())
        return SELECT_ACTION
    except:
        await update.message.reply_text("Valor inválido.")
        return SELECT_ACTION

# --- CENTRAL DE EXCLUSÃO (NOVA) ---
async def start_delete_hub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🗑️ <b>CENTRAL DE EXCLUSÃO</b>\nO que você deseja apagar?"
    kb = [
        [InlineKeyboardButton("💲 Transação (Gasto/Ganho)", callback_data='del_type_trans')],
        [InlineKeyboardButton("📂 Categoria", callback_data='del_type_cat')],
        [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]
    ]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return DELETE_HUB

async def delete_hub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    uid = initialize_user(query.from_user.id, query.from_user.username)

    if data == 'main_menu': return await back_to_menu(update, context)
    if data == 'start_delete_hub': return await start_delete_hub(update, context)

    # 1. Apagar Transação
    if data == 'del_type_trans':
        items = get_detailed_list(uid)
        if not items:
            await query.edit_message_text("📭 Nenhuma transação recente.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Voltar", callback_data='start_delete_hub')]]))
            return DELETE_HUB
        kb = []
        for item in items[:5]:
            icon = "🔴" if item[1] == 'expense' else "🟢"
            kb.append([InlineKeyboardButton(f"❌ {icon} R$ {item[2]} ({item[4]})", callback_data=f"del_id_{item[0]}")])
        kb.append([InlineKeyboardButton("🔢 Digitar ID", callback_data='type_del_id')])
        kb.append([InlineKeyboardButton("🔙 Voltar", callback_data='start_delete_hub')])
        await query.edit_message_text("❌ Clique para apagar:", reply_markup=InlineKeyboardMarkup(kb))
        return DELETE_HUB

    # 2. Apagar Categoria
    if data == 'del_type_cat':
        cats = get_categories(uid)
        kb = []
        for name, ctype, _ in cats:
            icon = "📉" if ctype == 'expense' else "📈"
            kb.append([InlineKeyboardButton(f"❌ {icon} {name}", callback_data=f"del_cat_{ctype}_{name}")])
        kb.append([InlineKeyboardButton("🔙 Voltar", callback_data='start_delete_hub')])
        await query.edit_message_text("📂 Clique na Categoria para apagar:", reply_markup=InlineKeyboardMarkup(kb))
        return DELETE_HUB

    # 3. Ações
    if data.startswith('del_id_'):
        delete_transaction(uid, int(data.replace('del_id_', '')))
        await query.edit_message_text("✅ Transação apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Apagar Mais", callback_data='del_type_trans'), InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]))
        return DELETE_HUB

    if data == 'type_del_id':
        await query.edit_message_text("🔢 <b>Digite o ID:</b>", parse_mode=ParseMode.HTML)
        return DEL_ID

    if data.startswith('del_cat_'):
        _, ctype, cname = data.split('_', 2)
        delete_category(uid, cname, ctype)
        await query.edit_message_text(f"✅ Categoria <b>{cname}</b> apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Apagar Mais", callback_data='del_type_cat'), InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
        return DELETE_HUB
    
    return DELETE_HUB

async def confirm_del_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tid = int(update.message.text)
        if delete_transaction(initialize_user(update.effective_user.id, update.effective_user.username), tid):
            await update.message.reply_text("✅ Apagado!", reply_markup=get_main_menu_keyboard())
        else: await update.message.reply_text("❌ ID não encontrado.", reply_markup=get_main_menu_keyboard())
    except: pass
    return SELECT_ACTION

# --- OUTROS ---
async def view_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = generate_chart(initialize_user(update.callback_query.from_user.id, update.callback_query.from_user.username))
    if buf: await update.callback_query.message.reply_photo(buf, caption="📊 Gastos")
    else: await update.callback_query.answer("Sem dados.")
    return SELECT_ACTION

async def view_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_summary(initialize_user(update.callback_query.from_user.id, update.callback_query.from_user.username))
    msg = f"📊 <b>RESUMO</b>\n🟢 R$ {s['income']:.2f}\n🔴 R$ {s['expense']:.2f}\n💰 <b>R$ {s['income']-s['expense']:.2f}</b>"
    kb = [[InlineKeyboardButton("Voltar", callback_data='main_menu')]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def view_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = initialize_user(query.from_user.id, query.from_user.username)
    items = get_detailed_list(uid)
    if not items:
        await query.edit_message_text("📭 Vazio.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Voltar", callback_data='main_menu')]]))
    else:
        report = "📋 <b>ÚLTIMOS LANÇAMENTOS:</b>\n"
        for item in items: report += f"🆔 <b>{item[0]}</b> | R$ {item[2]:.2f} ({item[3]})\n"
        await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]), parse_mode=ParseMode.HTML)
    return SELECT_ACTION

async def action_files_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("📄 PDF", callback_data='action_pdf'), InlineKeyboardButton("📊 Excel", callback_data='action_csv')], [InlineKeyboardButton("🔙 Voltar", callback_data='main_menu')]]
    await update.callback_query.edit_message_text("📂 Escolha:", reply_markup=InlineKeyboardMarkup(kb))
    return SELECT_ACTION

async def action_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("⏳ Gerando...")
    export_pdf(initialize_user(update.callback_query.from_user.id, update.callback_query.from_user.username), "extrato.pdf")
    await update.callback_query.message.reply_document(open("extrato.pdf", "rb"))
    return SELECT_ACTION

async def action_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    csv_data = export_csv(initialize_user(update.callback_query.from_user.id, update.callback_query.from_user.username))
    await update.callback_query.message.reply_document(document=io.BytesIO(csv_data.encode()), filename="planilha.csv")
    return SELECT_ACTION

async def backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_document(open("finance_bot.db", "rb"), caption="📦 Backup")
    return SELECT_ACTION

async def view_lixeira(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Atalho direto para o Delete Hub (Central de Exclusão)
    return await start_delete_hub(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Cancelado.", reply_markup=get_main_menu_keyboard())
    return SELECT_ACTION

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Financeiro - ONLINE 🟢"
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
def keep_alive(): 
    while True: 
        try: requests.get("http://127.0.0.1:10000") 
        except: pass
        time.sleep(600)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ACTION: [
                CallbackQueryHandler(start_gasto, pattern='^start_gasto$'),
                CallbackQueryHandler(start_ganho, pattern='^start_ganho$'),
                CallbackQueryHandler(view_extrato, pattern='^view_extrato$'),
                CallbackQueryHandler(view_chart, pattern='^view_chart$'),
                CallbackQueryHandler(view_cats, pattern='^view_cats$'),
                CallbackQueryHandler(view_details, pattern='^view_details$'),
                CallbackQueryHandler(start_delete_hub, pattern='^view_lixeira$'),
                CallbackQueryHandler(start_delete_hub, pattern='^start_delete_hub$'),
                CallbackQueryHandler(action_files_menu, pattern='^action_files$'),
                CallbackQueryHandler(action_pdf, pattern='^action_pdf$'),
                CallbackQueryHandler(action_csv, pattern='^action_csv$'),
                CallbackQueryHandler(backup_db, pattern='^backup_db$'),
                CallbackQueryHandler(start_new_cat_flow_from_menu, pattern='^new_cat_btn$'),
                CallbackQueryHandler(back_to_menu, pattern='^main_menu$')
            ],
            GASTO_VALOR: [MessageHandler(filters.TEXT, receive_gasto_valor)],
            GASTO_CAT: [CallbackQueryHandler(receive_gasto_cat)],
            GASTO_DESC: [CallbackQueryHandler(receive_gasto_desc), MessageHandler(filters.TEXT, receive_gasto_desc)],
            GANHO_VALOR: [MessageHandler(filters.TEXT, receive_ganho_valor)],
            GANHO_CAT: [CallbackQueryHandler(receive_ganho_cat)],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT, save_new_cat_name)],
            NEW_CAT_TYPE: [CallbackQueryHandler(save_new_cat_type)],
            CONFIRM_DEL_CAT: [
                CallbackQueryHandler(cat_options_handler, pattern='^opt_'),
                CallbackQueryHandler(cat_action_handler),
                CallbackQueryHandler(view_cats, pattern='^back_cats$'),
                CallbackQueryHandler(start_new_cat_flow_from_menu, pattern='^new_cat_btn$'),
                CallbackQueryHandler(back_to_menu, pattern='^main_menu$')
            ],
            SET_GOAL_VAL: [MessageHandler(filters.TEXT, save_goal)],
            # --- ROTA DA CENTRAL DE EXCLUSÃO ---
            DELETE_HUB: [
                CallbackQueryHandler(delete_hub_handler),
                CallbackQueryHandler(back_to_menu, pattern='^main_menu$')
            ],
            DEL_ID: [MessageHandler(filters.TEXT, confirm_del_id)]
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)]
    )
    
    app_bot.add_handler(conv)
    print("Bot Iniciado...")
    app_bot.run_polling(drop_pending_updates=True)
