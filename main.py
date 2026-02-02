# main.py - VERSÃO FINAL CORRIGIDA

import os
import sys
import subprocess
import json
import logging
import asyncio
from datetime import datetime

# ================= AUTO-INSTALAÇÃO DE DEPENDÊNCIAS =================
# Tenta importar. Se falhar, instala automaticamente sem precisar de requirements.txt
try:
    import httpx
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("⚠️ Dependências não encontradas. Iniciando instalação automática...")
    try:
        # Instala diretamente os pacotes necessários
        subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot", "httpx"])
        print("✅ Dependências instaladas! Reiniciando o script...")
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        print(f"❌ Falha crítica ao instalar dependências: {e}")
        sys.exit(1)

# ================= CONFIGURAÇÃO =================
# Tenta pegar do ambiente, senão avisa
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL")
DB_FILE = "db.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if not TOKEN:
    logger.error("❌ ERRO: Configure a variável de ambiente BOT_TOKEN ou TELEGRAM_TOKEN.")
    # Para evitar crash imediato em testes locais, mas impede o bot de rodar sem token
    if os.getenv("RENDER"): sys.exit(1)

# ================= SISTEMA DE ARQUIVOS (DB) =================
def get_empty_db():
    return {
        "transactions": [],
        "categories": {"gasto": ["Alimentação", "Transporte"], "ganho": ["Salário", "Extra"], "fixo": []},
        "goals": [],
        "fixed_costs": [],
        "users": {}
    }

def load_db():
    if not os.path.exists(DB_FILE):
        return get_empty_db()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        logger.warning("⚠️ Banco de dados corrompido ou não encontrado. Criando novo.")
        return get_empty_db()

def save_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar banco de dados: {e}")

db = load_db()

# ================= UTILITÁRIOS =================
def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

# ================= KEEP ALIVE (Para Render Free Tier) =================
async def keep_alive_async():
    if not RENDER_URL:
        logger.info("ℹ️ Keep-alive ignorado (RENDER_URL não definida).")
        return
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await asyncio.sleep(600) # Ping a cada 10 min
                response = await client.get(RENDER_URL, timeout=10)
                logger.info(f"🔄 Keep-alive ping: {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ Erro no Keep-alive: {e}")

# ================= MENUS E TECLADOS =================
def get_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Registrar Ganho", callback_data="add_income"),
         InlineKeyboardButton("💸 Registrar Gasto", callback_data="add_expense")],
        [InlineKeyboardButton("📂 Categorias", callback_data="categories"),
         InlineKeyboardButton("📌 Custos Fixos", callback_data="fixed")],
        [InlineKeyboardButton("🎯 Metas", callback_data="goals"),
         InlineKeyboardButton("📊 Relatório", callback_data="report")],
        [InlineKeyboardButton("🗑️ Limpar Dados", callback_data="trash")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="menu")]])

# ================= LÓGICA DO BOT (HANDLERS) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"mode": None}
        save_db(db)
    context.user_data.clear()
    await update.message.reply_text(
        "🤖 **FINANCEIRO PREMIUM**\nOlá! Eu ajudo você a controlar suas finanças.\n\nEscolha uma opção abaixo:",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "🤖 **MENU PRINCIPAL**\nO que deseja fazer?",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

# --- Fluxo de Adição de Valores ---
async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["mode"] = "ganho"
    await query.edit_message_text("💰 **NOVO GANHO**\nDigite o valor (ex: `1500.50`):", reply_markup=get_cancel_button(), parse_mode="Markdown")

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["mode"] = "gasto"
    await query.edit_message_text("💸 **NOVO GASTO**\nDigite o valor (ex: `25.90`):", reply_markup=get_cancel_button(), parse_mode="Markdown")

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cat_name = query.data.replace("cat_", "")
    value = context.user_data.get("value", 0)
    mode = context.user_data.get("mode")

    if not mode or value == 0:
        await query.edit_message_text("❌ Sessão expirada ou valor inválido.", reply_markup=get_menu())
        return

    # Salva transação
    db["transactions"].append({
        "type": mode,
        "value": value,
        "category": cat_name,
        "date": now()
    })
    save_db(db)

    emoji = "💰" if mode == "ganho" else "💸"
    await query.edit_message_text(
        f"✅ **REGISTRADO COM SUCESSO!**\n\n{emoji} Tipo: {mode.upper()}\n🏷️ Categoria: {cat_name}\n💲 Valor: R$ {value:.2f}",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )
    context.user_data.clear()

# --- Fluxo de Gerenciamento ---
async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text(
        "📂 **GERENCIAR CATEGORIAS**\nVocê pode adicionar novas categorias personalizadas.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Nova Categoria", callback_data="add_cat")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]
        ]),
        parse_mode="Markdown"
    )

async def add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_category"
    msg = (
        "Digite o TIPO e o NOME da categoria.\n"
        "Use: `tipo nome`\n\n"
        "Exemplos:\n"
        "`gasto Mercado`\n"
        "`ganho Freelance`"
    )
    await query.edit_message_text(msg, reply_markup=get_cancel_button(), parse_mode="Markdown")

async def fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_fixed"
    await query.edit_message_text(
        "📌 **CUSTO FIXO**\nDigite: `Nome Valor`\nEx: `Netflix 55.90`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

async def goals_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["state"] = "adding_goal"
    await query.edit_message_text(
        "🎯 **NOVA META**\nDigite: `Nome Limite`\nEx: `Lazer 300`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

# --- Relatório e Sistema ---
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    
    gastos = [t for t in db["transactions"] if t["type"] == "gasto"]
    ganhos = [t for t in db["transactions"] if t["type"] == "ganho"]
    
    total_gasto = sum(t["value"] for t in gastos)
    total_ganho = sum(t["value"] for t in ganhos)
    saldo = total_ganho - total_gasto

    # Correção do loop de resumo por categoria
    cat_summary = {}
    for t in gastos:
        cat_name = t["category"]
        cat_summary[cat_name] = cat_summary.get(cat_name, 0) + t["value"]

    text = f"📊 **RELATÓRIO FINANCEIRO**\n\n"
    text += f"💰 **Entradas:** R$ {total_ganho:.2f}\n"
    text += f"💸 **Saídas:** R$ {total_gasto:.2f}\n"
    text += f"────────────────\n"
    text += f"📈 **SALDO:** R$ {saldo:.2f}\n\n"

    if cat_summary:
        text += "📂 **Top Gastos por Categoria:**\n"
        # Ordena do maior para o menor gasto
        sorted_cats = sorted(cat_summary.items(), key=lambda item: item[1], reverse=True)
        for c, v in sorted_cats:
            text += f"• {c}: R$ {v:.2f}\n"
    else:
        text += "_Nenhum gasto registrado ainda._\n"

    if total_gasto > total_ganho:
        text += "\n⚠️ **ALERTA:** Você está no vermelho!"

    await query.edit_message_text(text, reply_markup=get_menu(), parse_mode="Markdown")

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    # Limpa dados mas mantém a estrutura de categorias padrão
    db["transactions"] = []
    db["goals"] = []
    db["fixed_costs"] = []
    save_db(db)
    await query.edit_message_text("🗑️ **LIXEIRA**\nTodos os registros de transações e metas foram apagados.", reply_markup=get_menu(), parse_mode="Markdown")

# --- Processador de Texto Geral ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    mode = context.user_data.get("mode")
    text = update.message.text.strip()

    # 1. Processando Valores Numéricos (Gasto/Ganho)
    if mode in ["ganho", "gasto"]:
        try:
            # Troca vírgula por ponto para aceitar formato brasileiro
            value = float(text.replace(",", "."))
            if value <= 0: raise ValueError
            
            context.user_data["value"] = value
            
            # Busca categorias disponíveis
            cats = db["categories"].get(mode, [])
            if not cats:
                # Se não houver categoria, cria uma "Geral" automaticamente
                cats = ["Geral"]
            
            # Cria botões
            keyboard = []
            row = []
            for c in cats:
                row.append(InlineKeyboardButton(c, callback_data=f"cat_{c}"))
                if len(row) == 2: # 2 botões por linha
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            keyboard.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")])

            await update.message.reply_text(
                f"Valor: R$ {value:.2f}\n📂 Agora escolha a **categoria**:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            # Remove o modo para não processar o próximo texto como valor
            context.user_data["mode"] = None 
            
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 10.50).")
        return

    # 2. Processando Comandos de Texto (Categorias, Fixos, Metas)
    if state in ["adding_category", "adding_fixed", "adding_goal"]:
        # Tenta separar por espaço
        if state == "adding_category":
            parts = text.split(" ", 1)
        else:
            parts = text.rsplit(" ", 1) # Pega o valor no final

        if len(parts) < 2:
            await update.message.reply_text("❌ Formato incorreto. Tente novamente ou clique em voltar.")
            return

        try:
            if state == "adding_category":
                tipo, nome = parts[0].lower(), parts[1]
                if tipo not in ["gasto", "ganho", "fixo"]:
                    await update.message.reply_text("❌ Tipo inválido. Use 'gasto', 'ganho' ou 'fixo'.")
                    return
                
                if nome not in db["categories"][tipo]:
                    db["categories"][tipo].append(nome)
                    save_db(db)
                    await update.message.reply_text(f"✅ Categoria **{nome}** adicionada em {tipo}!", reply_markup=get_menu(), parse_mode="Markdown")
                else:
                    await update.message.reply_text("⚠️ Essa categoria já existe.", reply_markup=get_menu())

            elif state == "adding_fixed":
                name, val_str = parts
                val = float(val_str.replace(",", "."))
                db["fixed_costs"].append({"name": name, "value": val, "date": now()})
                save_db(db)
                await update.message.reply_text(f"✅ Custo fixo **{name}** (R$ {val:.2f}) salvo!", reply_markup=get_menu(), parse_mode="Markdown")

            elif state == "adding_goal":
                name, val_str = parts
                val = float(val_str.replace(",", "."))
                db["goals"].append({"name": name, "limit": val, "spent": 0, "date": now()})
                save_db(db)
                await update.message.reply_text(f"🎯 Meta **{name}** (R$ {val:.2f}) criada!", reply_markup=get_menu(), parse_mode="Markdown")

        except ValueError:
            await update.message.reply_text("❌ O valor numérico está inválido.")
        except Exception as e:
            logger.error(f"Erro no handler de texto: {e}")
            await update.message.reply_text("❌ Ocorreu um erro interno.")
        
        # Limpa o estado após sucesso ou erro fatal
        context.user_data.clear()
    else:
        # Se o usuário digitar algo sem estar em um modo específico
        await update.message.reply_text("🤖 Não entendi. Por favor, use os botões do menu.", reply_markup=get_menu())

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Erro: TOKEN não encontrado. Defina a variável de ambiente.")
    else:
        # Inicia o Keep-Alive em background se tiver URL
        if RENDER_URL:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.create_task(keep_alive_async())

        # Configura e roda o Bot
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Adicionando handlers explicitamente em loop para compatibilidade
        handlers_list = [
            CommandHandler("start", start),
            CallbackQueryHandler(menu_callback, pattern="^menu$"),
            CallbackQueryHandler(add_income, pattern="^add_income$"),
            CallbackQueryHandler(add_expense, pattern="^add_expense$"),
            CallbackQueryHandler(categories, pattern="^categories$"),
            CallbackQueryHandler(add_category_prompt, pattern="^add_cat$"),
            CallbackQueryHandler(fixed_prompt, pattern="^fixed$"),
            CallbackQueryHandler(goals_prompt, pattern="^goals$"),
            CallbackQueryHandler(report, pattern="^report$"),
            CallbackQueryHandler(trash, pattern="^trash$"),
            # Handler genérico para botões de categoria (começam com cat_)
            CallbackQueryHandler(set_category, pattern="^cat_"),
            # Handler de texto (deve ser o último)
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        ]

        for handler in handlers_list:
            app.add_handler(handler)

        print("🤖 BOT INICIADO COM SUCESSO!")
        app.run_polling()
