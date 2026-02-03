import os
import sqlite3
import threading
import logging
import sys
import matplotlib
matplotlib.use('Agg') # Obrigatório para o Render
import matplotlib.pyplot as plt
import io
import csv
import requests
import time
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("⚠️ AVISO: Token não encontrado nas variáveis de ambiente.")

# Estados do Fluxo (Steps)
(GASTO_VALOR, GASTO_CAT, GASTO_DESC, GANHO_VALOR, GANHO_CAT, 
 NEW_CAT_NAME, NEW_CAT_TYPE, DEL_ID, CONFIRM_DEL_CAT, SET_GOAL_VAL, DELETE_HUB) = range(11)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- BANCO DE DADOS (SQLite) ---
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
            # Atualizações de colunas (para quem já tem o banco criado)
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

# --- FUNÇÕES DE BANCO DE DADOS ---
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

# --- MENUS (AQUI ESTÁ A MÁGICA DOS BOTÕES) ---

# 1. MENU FLUTUANTE (FIXO)
def get_main_menu_keyboard():
    keyboard = [
        ["📉 Novo Gasto", "📈 Novo Ganho"],
        ["📊 Extrato", "📂 Categorias"],
        ["📋 Detalhes", "📦 Backup"],
        ["🗑️ Apagar Coisas"]
    ]
    # resize_keyboard=True faz os botões ficarem com tamanho normal
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# 2. MENU CANCELAR (FIXO) - Usado quando você está digitando valores
def get_cancel_menu():
    return ReplyKeyboardMarkup([["🔙 Voltar ao Menu"]], resize_keyboard=True)

# 3. MENU INLINE (NA MENSAGEM) - Usado para sub-opções
def get_inline_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data='cancel')]])

# --- HANDLERS PRINCIPAIS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    initialize_user(user.id, user.username)
    await update.message.reply_text(
        f"👋 Olá <b>{user.first_name}</b>!\n\nBot Financeiro ONLINE 🟢\nUse o menu abaixo 👇", 
        reply_markup=get_main_menu_keyboard(), 
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

# Função para cancelar e voltar ao menu via botão de Texto
async def back_to_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 <b>Menu Principal</b>", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# Função para cancelar via botão Inline
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🚫 Ação cancelada.")
    return ConversationHandler.END

# --- FLUXO DE GASTOS ---
async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Envia mensagem e troca o teclado para "Voltar"
    await update.message.reply_text("📉 <b>NOVO GASTO</b>\nDigite o valor (ex: 20.00):", reply_markup=get_cancel_menu(), parse_mode=ParseMode.HTML)
    return GASTO_VALOR

async def receive_gasto_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Se o usuário clicar em "Voltar"
    if update.message.text == "🔙 Voltar ao Menu": return await back_to_menu_text(update, context)
    
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
        
        # Aqui usamos Inline Keyboard para selecionar a categoria (mais limpo)
        await update.message.reply_text(f"Valor: R$ {val:.2f}\n<b>Escolha a Categoria:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return GASTO_CAT
    except:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números.")
        return GASTO_VALOR

async def receive_gasto_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    if data == 'cancel': 
        await query.edit_message_text("🚫 Cancelado.")
        return ConversationHandler.END
        
    if data == 'create_new_cat_flow':
        await query.edit_message_text("✍️ <b>Nome da nova categoria:</b>", parse_mode=ParseMode.HTML)
        return NEW_CAT_NAME
    
    context.user_data['temp_cat'] = data.replace("cat_", "")
    # Pede a descrição usando Inline Keyboard para "Pular"
    await query.edit_message_text("📝 Digite a descrição (ou pule):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Pular", callback_data='skip_desc')]]))
    return GASTO_DESC

async def receive_gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Se for callback (botão pular)
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
    
    # Restaura o Menu Principal Flutuante
    await context.bot.send_message(chat_id=uid, text="🏠", reply_markup=get_main_menu_keyboard())
    await reply_func(msg, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- FLUXO DE GANHOS ---
async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 <b>NOVO GANHO</b>\nDigite o valor:", reply_markup=get_cancel_menu(), parse_mode=ParseMode.HTML)
    return GANHO_VALOR

async def receive_ganho_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Voltar ao Menu": return await back_to_menu_text(update, context)
    try:
        val = float(update.message.text.replace(',', '.'))
        context.user_data['temp_valor'] = val
        uid =
