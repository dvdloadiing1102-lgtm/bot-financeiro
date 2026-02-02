import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import threading
import time
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Configure TELEGRAM_TOKEN na Render")

# ================= KEEP ALIVE PARA RENDER =================

RENDER_URL = os.getenv("RENDER_URL", "https://bot-financeiro-hu1p.onrender.com")

def keep_alive():
    """Função para manter o bot acordado no Render"""
    while True:
        try:
            time.sleep(300)  # A cada 5 minutos
            response = requests.get(RENDER_URL, timeout=5)
            print(f"✅ Keep-alive ping: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Keep-alive erro: {e}")

# ================= DATABASE =================

conn = sqlite3.connect("finance.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    dark_mode INTEGER DEFAULT 1
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    type TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount REAL,
    category TEXT,
    description TEXT,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS incomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    value REAL,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS fixed_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    value REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    limit_value REAL
)
""")

conn.commit()

# ================= MEMORY =================

user_state = {}

# ================= HELPERS =================

def init_user(tid):
    cur.execute("INSERT OR IGNORE INTO users (telegram_id, dark_mode) VALUES (?, 1)", (tid,))
    conn.commit()

def get_user_dark_mode(tid):
    cur.execute("SELECT dark_mode FROM users WHERE telegram_id=?", (tid,))
    result = cur.fetchone()
    return result[0] if result else 1

def toggle_dark_mode(tid):
    current = get_user_dark_mode(tid)
    cur.execute("UPDATE users SET dark_mode=? WHERE telegram_id=?", (1 - current, tid))
    conn.commit()
    return 1 - current

def get_categories(uid, ctype):
    cur.execute("SELECT name FROM categories WHERE user_id=? AND type=?", (uid, ctype))
    return [x[0] for x in cur.fetchall()]

def add_category(uid, name, ctype):
    try:
        cur.execute("INSERT INTO categories (user_id, name, type) VALUES (?, ?, ?)", (uid, name, ctype))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao adicionar categoria: {e}")
        return False

def add_transaction(uid, t, amount, cat, desc):
    try:
        cur.execute("""
            INSERT INTO transactions (user_id, type, amount, category, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (uid, t, amount, cat, desc, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao adicionar transação: {e}")
        return False

def add_income(uid, name, value):
    try:
        cur.execute("INSERT INTO incomes (user_id, name, value, created_at) VALUES (?, ?, ?, ?)", 
                    (uid, name, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao adicionar renda: {e}")
        return False

def add_fixed_cost(uid, name, value):
    try:
        cur.execute("INSERT INTO fixed_costs (user_id, name, value) VALUES (?, ?, ?)", (uid, name, value))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao adicionar custo fixo: {e}")
        return False

def add_goal(uid, category, limit_value):
    try:
        cur.execute("INSERT INTO goals (user_id, category, limit_value) VALUES (?, ?, ?)", (uid, category, limit_value))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao adicionar meta: {e}")
        return False

def delete_transaction(tid):
    try:
        cur.execute("DELETE FROM transactions WHERE id=?", (tid,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao deletar transação: {e}")
        return False

def delete_income(iid):
    try:
        cur.execute("DELETE FROM incomes WHERE id=?", (iid,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao deletar renda: {e}")
        return False

def delete_category(cid):
    try:
        cur.execute("DELETE FROM categories WHERE id=?", (cid,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao deletar categoria: {e}")
        return False

def delete_fixed_cost(fcid):
    try:
        cur.execute("DELETE FROM fixed_costs WHERE id=?", (fcid,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao deletar custo fixo: {e}")
        return False

def delete_goal(gid):
    try:
        cur.execute("DELETE FROM goals WHERE id=?", (gid,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao deletar meta: {e}")
        return False

# ================= MENU =================

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📉 Novo Gasto", callback_data="gasto"),
         InlineKeyboardButton("📈 Novo Ganho", callback_data="ganho")],

        [InlineKeyboardButton("🏷️ Nova Categoria", callback_data="newcat"),
         InlineKeyboardButton("💼 Registrar Renda", callback_data="addrenda")],

        [InlineKeyboardButton("📦 Custo Fixo", callback_data="fixo"),
         InlineKeyboardButton("🎯 Definir Meta", callback_data="meta")],

        [InlineKeyboardButton("📊 Análise Completa", callback_data="analise")],
        [InlineKeyboardButton("📋 Histórico", callback_data="historico")],
        [InlineKeyboardButton("💰 Saldo", callback_data="saldo")],
        [InlineKeyboardButton("🗑️ Gerenciar", callback_data="gerenciar")],
        [InlineKeyboardButton("🌙 Modo Anti Sono", callback_data="toggle_dark")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_user(update.effective_user.id)
    await update.message.reply_text("🤖 Bot Financeiro Premium", reply_markup=menu())

# ================= VOLTAR =================

async def voltar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    if uid in user_state:
        del user_state[uid]
    await update.callback_query.edit_message_text("🤖 Bot Financeiro Premium", reply_markup=menu())

# ================= TOGGLE DARK MODE =================

async def toggle_dark_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    new_mode = toggle_dark_mode(uid)
    status = "🌙 Ativado" if new_mode == 1 else "☀️ Desativado"
    await update.callback_query.answer(f"Modo Anti Sono {status}", show_alert=True)
    await update.callback_query.edit_message_text("🤖 Bot Financeiro Premium", reply_markup=menu())

# ================= SALDO =================

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    
    # Transações
    cur.execute("SELECT type, amount FROM transactions WHERE user_id=?", (uid,))
    trans_rows = cur.fetchall()
    
    # Rendas
    cur.execute("SELECT value FROM incomes WHERE user_id=?", (uid,))
    income_rows = cur.fetchall()
    
    # Custos fixos
    cur.execute("SELECT value FROM fixed_costs WHERE user_id=?", (uid,))
    fixed_rows = cur.fetchall()
    
    total_trans_income = sum(r[1] for r in trans_rows if r[0] == "income")
    total_trans_expense = sum(r[1] for r in trans_rows if r[0] == "expense")
    total_income = sum(r[0] for r in income_rows)
    total_fixed = sum(r[0] for r in fixed_rows)
    
    saldo_total = total_income + total_trans_income - total_trans_expense - total_fixed
    
    msg = "💰 SALDO GERAL\n\n"
    msg += f"📈 Renda Total: R$ {total_income:.2f}\n"
    msg += f"📊 Transações Entrada: R$ {total_trans_income:.2f}\n"
    msg += f"📉 Transações Saída: R$ {total_trans_expense:.2f}\n"
    msg += f"📦 Custos Fixos: R$ {total_fixed:.2f}\n"
    msg += f"\n{'='*30}\n"
    msg += f"💵 SALDO FINAL: R$ {saldo_total:.2f}\n"
    
    if saldo_total >= 0:
        msg += "✅ Você está no positivo!"
    else:
        msg += "⚠️ Você está no negativo!"
    
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

# ================= GASTO / GANHO =================

async def start_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"type": "expense", "step": "value"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("💰 Digite o valor do gasto:", reply_markup=InlineKeyboardMarkup(buttons))

async def start_ganho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"type": "income", "step": "value"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("💰 Digite o valor do ganho:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    if uid not in user_state:
        return
    cat = update.callback_query.data.replace("cat_", "")
    user_state[uid]["category"] = cat
    user_state[uid]["step"] = "description"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("📝 Digite a descrição:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_category_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    if uid not in user_state:
        return
    user_state[uid]["category"] = "Múltiplas Categorias"
    user_state[uid]["step"] = "description"
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("📝 Digite a descrição:", reply_markup=InlineKeyboardMarkup(buttons))

# ================= NEW CATEGORY =================

async def new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "newcat", "step": "name"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite o nome da categoria:", reply_markup=InlineKeyboardMarkup(buttons))

async def save_cat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    
    if uid not in user_state or user_state[uid].get("mode") != "newcat":
        await update.callback_query.answer("Sessão expirada", show_alert=True)
        return
    
    ctype = "expense" if "expense" in update.callback_query.data else "income"
    name = user_state[uid].get("name")
    
    if not name:
        await update.callback_query.answer("Erro: nome não encontrado", show_alert=True)
        return
    
    if add_category(uid, name, ctype):
        del user_state[uid]
        await update.callback_query.edit_message_text("✅ Categoria criada com sucesso!", reply_markup=menu())
    else:
        await update.callback_query.answer("❌ Erro ao criar categoria", show_alert=True)

# ================= RENDA =================

async def renda_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "renda", "step": "name"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite o nome da renda:", reply_markup=InlineKeyboardMarkup(buttons))

# ================= CUSTO FIXO =================

async def fixed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "fixo", "step": "name"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite o nome do custo fixo:", reply_markup=InlineKeyboardMarkup(buttons))

# ================= META =================

async def meta_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"mode": "meta", "step": "category"}
    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text("Digite a categoria da meta:", reply_markup=InlineKeyboardMarkup(buttons))

# ================= GERENCIAR (DELETE) =================

async def gerenciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("🗑️ Deletar Transação", callback_data="del_trans")],
        [InlineKeyboardButton("🗑️ Deletar Renda", callback_data="del_income")],
        [InlineKeyboardButton("🗑️ Deletar Categoria", callback_data="del_cat")],
        [InlineKeyboardButton("🗑️ Deletar Custo Fixo", callback_data="del_fixed")],
        [InlineKeyboardButton("🗑️ Deletar Meta", callback_data="del_goal")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]
    ]
    await update.callback_query.edit_message_text("🗑️ O que deseja deletar?", reply_markup=InlineKeyboardMarkup(buttons))

async def del_trans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT id, amount, category, description, created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    
    if not rows:
        await update.callback_query.answer("Nenhuma transação para deletar", show_alert=True)
        return
    
    buttons = [[InlineKeyboardButton(f"R$ {r[1]:.2f} - {r[2]} ({r[3]})", callback_data=f"deltrans_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="gerenciar")])
    await update.callback_query.edit_message_text("Selecione a transação para deletar:", reply_markup=InlineKeyboardMarkup(buttons))

async def deltrans_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = int(update.callback_query.data.replace("deltrans_", ""))
    if delete_transaction(tid):
        await update.callback_query.edit_message_text("✅ Transação deletada!", reply_markup=menu())
    else:
        await update.callback_query.answer("❌ Erro ao deletar", show_alert=True)

async def del_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT id, name, value FROM incomes WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    
    if not rows:
        await update.callback_query.answer("Nenhuma renda para deletar", show_alert=True)
        return
    
    buttons = [[InlineKeyboardButton(f"{r[1]} - R$ {r[2]:.2f}", callback_data=f"delinc_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="gerenciar")])
    await update.callback_query.edit_message_text("Selecione a renda para deletar:", reply_markup=InlineKeyboardMarkup(buttons))

async def delinc_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iid = int(update.callback_query.data.replace("delinc_", ""))
    if delete_income(iid):
        await update.callback_query.edit_message_text("✅ Renda deletada!", reply_markup=menu())
    else:
        await update.callback_query.answer("❌ Erro ao deletar", show_alert=True)

async def del_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT id, name, type FROM categories WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    
    if not rows:
        await update.callback_query.answer("Nenhuma categoria para deletar", show_alert=True)
        return
    
    buttons = [[InlineKeyboardButton(f"{r[1]} ({r[2]})", callback_data=f"delcat_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="gerenciar")])
    await update.callback_query.edit_message_text("Selecione a categoria para deletar:", reply_markup=InlineKeyboardMarkup(buttons))

async def delcat_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = int(update.callback_query.data.replace("delcat_", ""))
    if delete_category(cid):
        await update.callback_query.edit_message_text("✅ Categoria deletada!", reply_markup=menu())
    else:
        await update.callback_query.answer("❌ Erro ao deletar", show_alert=True)

async def del_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT id, name, value FROM fixed_costs WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    
    if not rows:
        await update.callback_query.answer("Nenhum custo fixo para deletar", show_alert=True)
        return
    
    buttons = [[InlineKeyboardButton(f"{r[1]} - R$ {r[2]:.2f}", callback_data=f"delfixed_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="gerenciar")])
    await update.callback_query.edit_message_text("Selecione o custo fixo para deletar:", reply_markup=InlineKeyboardMarkup(buttons))

async def delfixed_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fcid = int(update.callback_query.data.replace("delfixed_", ""))
    if delete_fixed_cost(fcid):
        await update.callback_query.edit_message_text("✅ Custo fixo deletado!", reply_markup=menu())
    else:
        await update.callback_query.answer("❌ Erro ao deletar", show_alert=True)

async def del_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT id, category, limit_value FROM goals WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    
    if not rows:
        await update.callback_query.answer("Nenhuma meta para deletar", show_alert=True)
        return
    
    buttons = [[InlineKeyboardButton(f"{r[1]} - R$ {r[2]:.2f}", callback_data=f"delgoal_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="gerenciar")])
    await update.callback_query.edit_message_text("Selecione a meta para deletar:", reply_markup=InlineKeyboardMarkup(buttons))

async def delgoal_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = int(update.callback_query.data.replace("delgoal_", ""))
    if delete_goal(gid):
        await update.callback_query.edit_message_text("✅ Meta deletada!", reply_markup=menu())
    else:
        await update.callback_query.answer("❌ Erro ao deletar", show_alert=True)

# ================= UNIVERSAL TEXT HANDLER =================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()
    
    if uid not in user_state:
        return
    
    state = user_state[uid]
    step = state.get("step")
    mode = state.get("mode")
    
    try:
        # ===== GASTO/GANHO - VALOR =====
        if step == "value" and mode is None:
            val = float(text.replace(",", "."))
            state["value"] = val
            state["step"] = "category"
            
            ctype = "expense" if state["type"] == "expense" else "income"
            cats = get_categories(uid, ctype)
            
            if not cats:
                await update.message.reply_text("❗ Cadastre uma categoria primeiro", reply_markup=menu())
                del user_state[uid]
                return
            
            buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in cats]
            buttons.append([InlineKeyboardButton("✅ Múltiplas Categorias", callback_data="cat_all")])
            buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")])
            await update.message.reply_text("📂 Escolha categoria:", reply_markup=InlineKeyboardMarkup(buttons))
        
        # ===== GASTO/GANHO - DESCRIÇÃO =====
        elif step == "description" and mode is None:
            if "value" in state and "category" in state:
                if add_transaction(uid, state["type"], state["value"], state["category"], text):
                    del user_state[uid]
                    await update.message.reply_text("✅ Registro salvo com sucesso!", reply_markup=menu())
                else:
                    await update.message.reply_text("❌ Erro ao salvar. Tente novamente.", reply_markup=menu())
            else:
                await update.message.reply_text("❌ Erro ao processar", reply_markup=menu())
        
        # ===== CATEGORIA - NOME =====
        elif step == "name" and mode == "newcat":
            state["name"] = text
            state["step"] = "type"
            buttons = [
                [InlineKeyboardButton("📉 Gasto", callback_data="type_expense")],
                [InlineKeyboardButton("📈 Ganho", callback_data="type_income")],
                [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]
            ]
            await update.message.reply_text("Escolha o tipo da categoria:", reply_markup=InlineKeyboardMarkup(buttons))
        
        # ===== RENDA - NOME =====
        elif step == "name" and mode == "renda":
            state["name"] = text
            state["step"] = "value"
            buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
            await update.message.reply_text("Digite o valor da renda:", reply_markup=InlineKeyboardMarkup(buttons))
        
        # ===== RENDA - VALOR =====
        elif step == "value" and mode == "renda":
            val = float(text.replace(",", "."))
            if add_income(uid, state["name"], val):
                del user_state[uid]
                await update.message.reply_text("✅ Renda salva com sucesso! 💰", reply_markup=menu())
            else:
                await update.message.reply_text("❌ Erro ao salvar. Tente novamente.", reply_markup=menu())
        
        # ===== CUSTO FIXO - NOME =====
        elif step == "name" and mode == "fixo":
            state["name"] = text
            state["step"] = "value"
            buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
            await update.message.reply_text("Digite o valor do custo:", reply_markup=InlineKeyboardMarkup(buttons))
        
        # ===== CUSTO FIXO - VALOR =====
        elif step == "value" and mode == "fixo":
            val = float(text.replace(",", "."))
            if add_fixed_cost(uid, state["name"], val):
                del user_state[uid]
                await update.message.reply_text("✅ Custo fixo cadastrado com sucesso!", reply_markup=menu())
            else:
                await update.message.reply_text("❌ Erro ao salvar. Tente novamente.", reply_markup=menu())
        
        # ===== META - CATEGORIA =====
        elif step == "category" and mode == "meta":
            state["category"] = text
            state["step"] = "value"
            buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
            await update.message.reply_text("Digite o valor limite da meta:", reply_markup=InlineKeyboardMarkup(buttons))
        
        # ===== META - VALOR =====
        elif step == "value" and mode == "meta":
            val = float(text.replace(",", "."))
            if add_goal(uid, state["category"], val):
                del user_state[uid]
                await update.message.reply_text("🎯 Meta salva com sucesso!", reply_markup=menu())
            else:
                await update.message.reply_text("❌ Erro ao salvar. Tente novamente.", reply_markup=menu())
    
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite um número válido.")
    except Exception as e:
        print(f"Erro: {e}")
        await update.message.reply_text(f"❌ Erro ao processar: {str(e)}")

# ================= ANALISE DETALHADA =================

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    cur.execute("SELECT id, type, amount, category, description, created_at FROM transactions WHERE user_id=? ORDER BY id DESC", (uid,))
    rows = cur.fetchall()

    if not rows:
        buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
        await update.callback_query.edit_message_text("📭 Sem transações registradas", reply_markup=InlineKeyboardMarkup(buttons))
        return

    total_inc = sum(r[2] for r in rows if r[1] == "income")
    total_exp = sum(r[2] for r in rows if r[1] == "expense")
    
    # Análise por categoria
    cat_analysis = {}
    for r in rows:
        cat = r[3]
        if cat not in cat_analysis:
            cat_analysis[cat] = {"income": 0, "expense": 0}
        if r[1] == "income":
            cat_analysis[cat]["income"] += r[2]
        else:
            cat_analysis[cat]["expense"] += r[2]

    msg = "📊 ANÁLISE DETALHADA\n"
    msg += "="*40 + "\n\n"
    
    msg += "💰 RESUMO GERAL\n"
    msg += f"📈 Total Ganho: R$ {total_inc:.2f}\n"
    msg += f"📉 Total Gasto: R$ {total_exp:.2f}\n"
    msg += f"💵 Saldo: R$ {total_inc-total_exp:.2f}\n\n"
    
    msg += "📂 ANÁLISE POR CATEGORIA\n"
    msg += "-"*40 + "\n"
    for cat, data in cat_analysis.items():
        msg += f"\n{cat}:\n"
        if data["income"] > 0:
            msg += f"  ✅ Entrada: R$ {data['income']:.2f}\n"
        if data["expense"] > 0:
            msg += f"  ❌ Saída: R$ {data['expense']:.2f}\n"
    
    msg += "\n\n📋 ÚLTIMAS TRANSAÇÕES\n"
    msg += "-"*40 + "\n"
    for r in rows[:20]:
        emoji = "✅" if r[1] == "income" else "❌"
        msg += f"{emoji} {r[5]} | R$ {r[2]:.2f}\n"
        msg += f"   📂 {r[3]} | {r[4]}\n\n"

    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

# ================= HISTÓRICO =================

async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    cur.execute("SELECT id, amount, category, description, created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,))
    rows = cur.fetchall()

    if not rows:
        buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
        await update.callback_query.edit_message_text("📭 Sem registros", reply_markup=InlineKeyboardMarkup(buttons))
        return

    msg = "📋 HISTÓRICO (Últimas 30 transações)\n\n"
    for r in rows:
        msg += f"🕒 {r[4]}\n"
        msg += f"💰 R$ {r[1]:.2f} | 📂 {r[2]}\n"
        msg += f"📝 {r[3]}\n"
        msg += f"🗑️ ID: {r[0]}\n\n"

    buttons = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")]]
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(voltar, pattern="^voltar$"))
    app.add_handler(CallbackQueryHandler(toggle_dark_mode_handler, pattern="^toggle_dark$"))
    app.add_handler(CallbackQueryHandler(start_gasto, pattern="^gasto$"))
    app.add_handler(CallbackQueryHandler(start_ganho, pattern="^ganho$"))
    app.add_handler(CallbackQueryHandler(new_cat, pattern="^newcat$"))
    app.add_handler(CallbackQueryHandler(save_cat_type, pattern="^type_"))
    app.add_handler(CallbackQueryHandler(choose_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(choose_category_all, pattern="^cat_all$"))
    app.add_handler(CallbackQueryHandler(renda_start, pattern="^addrenda$"))
    app.add_handler(CallbackQueryHandler(fixed_start, pattern="^fixo$"))
    app.add_handler(CallbackQueryHandler(meta_start, pattern="^meta$"))
    app.add_handler(CallbackQueryHandler(analise, pattern="^analise$"))
    app.add_handler(CallbackQueryHandler(historico, pattern="^historico$"))
    app.add_handler(CallbackQueryHandler(saldo, pattern="^saldo$"))
    app.add_handler(CallbackQueryHandler(gerenciar, pattern="^gerenciar$"))
    
    # Delete handlers
    app.add_handler(CallbackQueryHandler(del_trans, pattern="^del_trans$"))
    app.add_handler(CallbackQueryHandler(del_income, pattern="^del_income$"))
    app.add_handler(CallbackQueryHandler(del_cat, pattern="^del_cat$"))
    app.add_handler(CallbackQueryHandler(del_fixed, pattern="^del_fixed$"))
    app.add_handler(CallbackQueryHandler(del_goal, pattern="^del_goal$"))
    
    app.add_handler(CallbackQueryHandler(deltrans_confirm, pattern="^deltrans_"))
    app.add_handler(CallbackQueryHandler(delinc_confirm, pattern="^delinc_"))
    app.add_handler(CallbackQueryHandler(delcat_confirm, pattern="^delcat_"))
    app.add_handler(CallbackQueryHandler(delfixed_confirm, pattern="^delfixed_"))
    app.add_handler(CallbackQueryHandler(delgoal_confirm, pattern="^delgoal_"))

    # Text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 FINANCEIRO PREMIUM ONLINE - KEEP ALIVE ATIVADO")
    app.run_polling()

if __name__ == "__main__":
    # Inicia thread de keep-alive
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    print("✅ Keep-Alive iniciado!")
    
    # Inicia o bot
    main()
