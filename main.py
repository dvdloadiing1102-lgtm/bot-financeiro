import os
import sqlite3
import threading
import logging
import sys
import io
import csv
import requests
import time
from datetime import datetime
from flask import Flask

# Matplotlib para gráficos
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Telegram Libraries
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# PDF Libraries
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("AVISO: Token não configurado.")

# Estados do Fluxo
(GASTO_VALOR, GASTO_CAT, GASTO_DESC, GANHO_VALOR, GANHO_CAT, 
 NEW_CAT_NAME, NEW_CAT_TYPE, DEL_ID, CONFIRM_DEL_CAT, SET_GOAL_VAL, DELETE_HUB) = range(11)

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
            c.execute("""CREATE TABLE IF NOT EXISTS users 
                         (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, username TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS categories 
                         (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, cat_type TEXT DEFAULT 'expense', goal_limit REAL DEFAULT 0)""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions 
                         (id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT, amount REAL, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
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
            for name in cats_exp: 
                c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, 'expense')", (uid, name))
            cats_inc = ["Salario", "Extra", "Vendas"]
            for name in cats_inc: 
                c.execute("INSERT INTO categories (user_id, name, cat_type) VALUES (?, ?, 'income')", (uid, name))
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

# --- MENUS ---

# 1. Menu Flutuante (Fixo)
def get_main_menu_keyboard():
    keyboard = [
        ["📉 Novo Gasto", "📈 Novo Ganho"],
        ["📊 Extrato", "📂 Categorias"],
        ["📦 Backup", "🗑️ Apagar"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# 2. Menu Voltar Flutuante
def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["🔙 Voltar"]], resize_keyboard=True, one_time_keyboard=False)

# --- HANDLERS DE NAVEGAÇÃO ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    initialize_user(user.id, user.username)
    await update.message.reply_text(
        f"👋 Olá <b>{user.first_name}</b>!\n\nBot Financeiro ONLINE 🟢", 
        reply_markup=get_main_menu_keyboard(), 
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 <b>Menu Principal</b>", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def cancel_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await update.effective_message.reply_text("🚫 Cancelado.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- 1. CENTRAL DE EXCLUSÃO (CORRIGIDA) ---
async def start_delete_hub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Identifica se veio de botão ou callback
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
    else:
        msg_func = update.message.reply_text
    
    msg = "🗑️ <b>CENTRAL DE EXCLUSÃO</b>\nSelecione o que apagar:"
    kb = [
        [InlineKeyboardButton("💲 Transações Recentes", callback_data='del_mode_trans')],
        [InlineKeyboardButton("📂 Categoria Inteira", callback_data='del_mode_cat')],
        [InlineKeyboardButton("❌ Sair", callback_data='cancel_action')]
    ]
    
    await msg_func(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return DELETE_HUB

async def delete_hub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = initialize_user(query.from_user.id, query.from_user.username)

    if data == 'cancel_action':
        await query.edit_message_text("🏠 Voltando...", parse_mode=ParseMode.HTML)
        await context.bot.send_message(chat_id=uid, text="Menu:", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    if data == 'del_mode_trans':
        items = get_detailed_list(uid)
        if not items:
            await query.edit_message_text("📭 Nada para apagar.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Voltar", callback_data='back_hub')]]))
            return DELETE_HUB
        
        kb = []
        for item in items[:5]: 
            icon = "🔴" if item[1] == 'expense' else "🟢"
            # Botão delete direto
            btn_text = f"🗑️ {icon} R$ {item[2]} ({item[4]})"
            kb.append([InlineKeyboardButton(btn_text, callback_data=f"del_id_{item[0]}")])
        
        kb.append([InlineKeyboardButton("🔢 Digitar ID", callback_data='manual_id')])
        kb.append([InlineKeyboardButton("🔙 Voltar", callback_data='back_hub')])
        
        await query.edit_message_text("❌ Clique para apagar:", reply_markup=InlineKeyboardMarkup(kb))
        return DELETE_HUB

    if data == 'del_mode_cat':
        cats = get_categories(uid)
        kb = []
        for name, ctype, _ in cats:
            icon = "📉" if ctype == 'expense' else "📈"
            kb.append([InlineKeyboardButton(f"🗑️ {icon} {name}", callback_data=f"del_cat_{ctype}_{name}")])
        kb.append([InlineKeyboardButton("🔙 Voltar", callback_data='back_hub')])
        await query.edit_message_text("📂 Apagar Categoria:", reply_markup=InlineKeyboardMarkup(kb))
        return DELETE_HUB

    if data.startswith('del_id_'):
        tid = int(data.replace('del_id_', ''))
        delete_transaction(uid, tid)
        # Recarrega a lista para mostrar que sumiu
        return await delete_hub_handler(update, context) # Recursivo seguro aqui pois muda o estado dos dados

    if data.startswith('del_cat_'):
        _, ctype, cname = data.split('_', 2)
        delete_category(uid, cname, ctype)
        await query.edit_message_text(f"✅ Categoria <b>{cname}</b> apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data='back_hub')]]), parse_mode=ParseMode.HTML)
        return DELETE_HUB

    if data == 'back_hub':
        return await start_delete_hub(update, context)

    if data == 'manual_id':
        await query.edit_message_text("🔢 <b>Digite o ID:</b>", parse_mode=ParseMode.HTML)
        return DEL_ID

    return DELETE_HUB

async def confirm_del_id_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Voltar": return await back_to_main(update, context)
    
    uid = initialize_user(update.effective_user.id, update.effective_user.username)
    try:
        tid = int(text)
        if delete_transaction(uid, tid):
            await update.message.reply_text("✅ Apagado!", reply_markup=get_main_menu_keyboard())
        else:
            await update.message.reply_text("❌ ID não encontrado.", reply_markup=get_main_menu_keyboard())
    except:
        await update.message.reply_text("❌ Número inválido.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- 2. FLUXO GASTO ---
async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📉 <b>NOVO GASTO</b>\nDigite o valor (ex: 20.00):", reply_markup=get_cancel_keyboard(), parse_mode=ParseMode.HTML)
    return GASTO_VALOR

async def receive_gasto_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Voltar": return await back_to_main(update, context)
    
    # Se clicou em outro botão do menu principal
    if text in ["📉 Novo Gasto", "📈 Novo Ganho", "🗑️ Apagar"]:
        return ConversationHandler.END 

    try:
        val = float(text.replace(',', '.'))
        context.user_data['temp_valor'] = val
        uid = initialize_user(update.effective_user.id, update.effective_user.username)
        cats = get_categories(uid, 'expense')
        
        kb = []
        row = []
        for c in cats:
            row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
            if len(row) == 2: kb.append(row); row = []
        if row: kb.append(row)
        
        kb.append([InlineKeyboardButton("➕ Criar Nova", callback_data='create_new_cat_flow')])
        kb.append([InlineKeyboardButton("❌ Cancelar", callback_data='cancel_action')])
        
        await update.message.reply_text(f"Valor: R$ {val:.2f}\n<b>Escolha a Categoria:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        return GASTO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return GASTO_VALOR

async def receive_gasto_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    if data == 'cancel_action': return await cancel_inline(update, context)
    
    if data == 'create_new_cat_flow':
        await query.edit_message_text("✍️ <b>Nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    
    context.user_data['temp_cat'] = data.replace("cat_", "")
    kb = [[InlineKeyboardButton("Pular Descrição", callback_data='skip_desc')]]
    await query.edit_message_text("📝 Digite a descrição (ou pule):", reply_markup=InlineKeyboardMarkup(kb))
    return GASTO_DESC

async def receive_gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        desc = "Gasto"; uid = update.callback_query.from_user.id; msg_func = update.callback_query.message.reply_text
        uname = update.callback_query.from_user.username
    else:
        desc = update.message.text; uid = update.effective_user.id; msg_func = update.message.reply_text
        uname = update.effective_user.username
        if desc == "🔙 Voltar": return await back_to_main(update, context)

    real_uid = initialize_user(uid, uname)
    val = context.user_data['temp_valor']
    cat = context.user_data['temp_cat']
    alert = check_goal(real_uid, cat, val)
    add_transaction(real_uid, "expense", val, cat, desc)
    
    final_msg = f"✅ <b>Gasto Salvo!</b>\nR$ {val:.2f} em {cat}."
    if alert: final_msg += f"\n\n{alert}"
    
    await context.bot.send_message(chat_id=uid, text="🏠", reply_markup=get_main_menu_keyboard())
    if update.callback_query:
        await update.callback_query.edit_message_text(final_msg, parse_mode=ParseMode.HTML)
    else:
        await msg_func(final_msg, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- 3. FLUXO GANHO ---
async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 <b>NOVO GANHO</b>\nDigite o valor:", reply_markup=get_cancel_keyboard(), parse_mode=ParseMode.HTML)
    return GANHO_VALOR

async def receive_ganho_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Voltar": return await back_to_main(update, context)
    
    try:
        val = float(text.replace(',', '.'))
        context.user_data['temp_valor'] = val
        uid = initialize_user(update.effective_user.id, update.effective_user.username)
        cats = get_categories(uid, 'income')
        kb = []
        for c in cats: kb.append([InlineKeyboardButton(c, callback_data=f"inc_{c}")])
        kb.append([InlineKeyboardButton("➕ Criar Nova", callback_data='create_new_cat_flow')])
        
        await update.message.reply_text("Fonte:", reply_markup=InlineKeyboardMarkup(kb))
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
    uid = query.from_user.id
    add_transaction(initialize_user(uid, query.from_user.username), "income", context.user_data['temp_valor'], fonte, "Entrada")
    
    await context.bot.send_message(chat_id=uid, text="🏠", reply_markup=get_main_menu_keyboard())
    await query.edit_message_text("✅ <b>Ganho Salvo!</b>", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- 4. CATEGORIAS ---
async def start_view_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = initialize_user(update.effective_user.id, update.effective_user.username)
    cats = get_categories(uid)
    kb = []
    for name, ctype, goal in cats:
        icon = "📉" if ctype == 'expense' else "📈"
        goal_txt = f" (Meta: {goal})" if goal > 0 else ""
        kb.append([InlineKeyboardButton(f"{icon} {name}{goal_txt}", callback_data=f"opt_{ctype}_{name}")])
    kb.append([InlineKeyboardButton("➕ Criar Nova", callback_data='create_new_cat_flow')])
    kb.append([InlineKeyboardButton("❌ Fechar", callback_data='cancel_action')])
    
    await update.message.reply_text("📂 <b>CATEGORIAS</b>\nClique para editar ou criar meta:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return CONFIRM_DEL_CAT

async def save_new_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Voltar": return await back_to_main(update, context)
    context.user_data['new_cat_name'] = update.message.text
    kb = [[InlineKeyboardButton("Gasto", callback_data='type_expense'), InlineKeyboardButton("Ganho", callback_data='type_income')]]
    await update.message.reply_text("Essa categoria é de:", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def save_new_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cat_type = query.data.replace("type_", "")
    uid = initialize_user(query.from_user.id, query.from_user.username)
    add_category(uid, context.user_data['new_cat_name'], cat_type)
    
    await context.bot.send_message(chat_id=uid, text="🏠", reply_markup=get_main_menu_keyboard())
    await query.edit_message_text(f"✅ Categoria <b>{context.user_data['new_cat_name']}</b> criada!", parse_mode=ParseMode.HTML)
    return ConversationHandler.END
