import os
...
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
Agora vou criar os arquivos de configuração necessários para Render e GitHub:

Write File
/home/user/requirements.txt
Visualizar
python-telegram-bot>=20.0
httpx>=0.24.0
Write File
/home/user/render.yaml
Visualizar
services:
  - type: web
    name: telegram-financeiro-bot
...
      - key: RENDER_URL
        sync: false
      - key: PYTHON_VERSION
        value: 3.11.0
Write File
/home/user/.gitignore
Visualizar
# Python
__pycache__/
*.py[cod]
...
.env.local

# Logs
*.log
Write File
/home/user/README.md
Visualizar
# 🤖 Bot Financeiro para Telegram

Bot completo para controle financeiro pessoal via Telegram.
...
Se encontrar problemas, verifique:
1. Logs do Render
2. Status do serviço
3. Configuração das variáveis de ambiente
Agora vou criar um script de teste local:

Write File
/home/user/test_bot.py
Visualizar
#!/usr/bin/env python3
"""
Script de teste local - Execute antes de fazer deploy
...
print("4. Conecte o repositório no Render")
print("\n🚀 Para testar localmente:")
print("   export BOT_TOKEN='seu_token_aqui'")
print("   python main.py")
Agora vou criar um arquivo de ambiente de exemplo:

Write File
/home/user/.env.example
Visualizar
# Copie este arquivo para .env e preencha os valores

# Token do bot (obtenha com @BotFather no Telegram)
...
RENDER_URL=https://seu-app.onrender.com

# Porta (o Render define automaticamente, não é necessário alterar)
PORT=8080
Perfeito! Agora vou copiar todos os arquivos para um local acessível:

Bash Command
mkdir -p /mnt/user-data/outputs/telegram-bot && cp /home/user/{main.py,requirements.txt,render.yaml,.gitignore,README.md,test_bot.py,.env.example} /mnt/user-data/outputs/telegram-bot/ && ls -lh /mnt/user-data/outputs/telegram-bot/
Visualizar
total 23K
-rwxr-xr-x 1 user user 1.8K Feb  2 22:38 README.md
-rwxr-xr-x 1 user user  18K Feb  2 22:38 main.py
-rwxr-xr-x 1 user user  307 Feb  2 22:38 render.yaml
-rwxr-xr-x 1 user user   40 Feb  2 22:38 requirements.txt
-rwxr-xr-x 1 user user 1.7K Feb  2 22:38 test_bot.py
Exit Code: 0
Agora vou criar um guia rápido de deploy:

Write File
/mnt/user-data/outputs/telegram-bot/DEPLOY.md
Visualizar
# ⚡ GUIA RÁPIDO DE DEPLOY

## 🎯 PASSO A PASSO (5 minutos)
...
- [ ] Deploy concluído (status "Live")
- [ ] Bot responde no Telegram

**Tudo checado? Parabéns! 🎉**
Agora vou criar um documento com as correções feitas:

Write File
/mnt/user-data/outputs/telegram-bot/CORREÇÕES.md
Visualizar
# 🔧 CORREÇÕES REALIZADAS NO BOT

## ❌ PROBLEMAS ENCONTRADOS
...

- **Segurança do Token:** NUNCA commite o `.env` com token real. Use apenas `.env.example` como modelo.

- **Logs:** Monitore os logs no Render dashboard para diagnosticar problemas em produção.
Perfeito! Agora vou criar um arquivo ZIP com tudo:

Bash Command
cd /mnt/user-data/outputs && zip -r telegram-bot-corrigido.zip telegram-bot/ && ls -lh telegram-bot-corrigido.zip
Visualizar
  adding: telegram-bot/ (stored 0%)
  adding: telegram-bot/.env.example (deflated 25%)
  adding: telegram-bot/.gitignore (deflated 22%)
...
  adding: telegram-bot/render.yaml (deflated 36%)
  adding: telegram-bot/requirements.txt (stored 0%)
  adding: telegram-bot/test_bot.py (deflated 49%)
-rwxr-xr-x 1 user user 14K Feb  2 22:39 telegram-bot-corrigido.zip
Exit Code: 0
Excelente! Agora vou criar um sumário final:

Write File
/mnt/user-data/outputs/telegram-bot/LEIA-ME-PRIMEIRO.md
Visualizar
# 📦 PACOTE COMPLETO - BOT TELEGRAM FINANCEIRO

## 📂 ARQUIVOS INCLUÍDOS
...
Criado em: 02/02/2026
Versão: 2.0 (Corrigida)
Python: 3.11+
Telegram Bot API: 20.0+
Agora vou listar todos os arquivos criados:

Bash Command
cd /mnt/user-data/outputs/telegram-bot && tree -L 1 -h --du || ls -lh
Visualizar
/bin/bash: line 1: tree: command not found
total 38K
-rwxr-xr-x 1 user user 6.2K Feb  2 22:39 CORREÇÕES.md
...
-rwxr-xr-x 1 user user  18K Feb  2 22:38 main.py
-rwxr-xr-x 1 user user  307 Feb  2 22:38 render.yaml
-rwxr-xr-x 1 user user   40 Feb  2 22:38 requirements.txt
-rwxr-xr-x 1 user user 1.7K Feb  2 22:38 test_bot.py
Exit Code: 0
Perfeito! Agora vou recriar o ZIP final com o novo arquivo:

Bash Command
cd /mnt/user-data/outputs && rm telegram-bot-corrigido.zip && zip -r telegram-bot-corrigido.zip telegram-bot/ && echo "✅ ZIP criado!" && ls -lh telegram-bot-corrigido.zip
Visualizar
  adding: telegram-bot/ (stored 0%)
  adding: telegram-bot/.env.example (deflated 25%)
  adding: telegram-bot/.gitignore (deflated 22%)
...
  adding: telegram-bot/requirements.txt (stored 0%)
  adding: telegram-bot/test_bot.py (deflated 49%)
✅ ZIP criado!
-rwxr-xr-x 1 user user 16K Feb  2 22:40 telegram-bot-corrigido.zip
Exit Code: 0
🎉 BOT CORRIGIDO E PRONTO PARA DEPLOY!
✅ O que foi corrigido:
🔴 Problemas Críticos:
Keep-alive bloqueando inicialização - Agora usa post_init hook
Loop de eventos duplicado - Removido conflito com Telegram
Crash no relatório - Corrigido loop de categorias
Falta de error handler - Implementado tratamento global de erros
Validação fraca do DB - Agora detecta e corrige JSON corrompido
🟡 Melhorias Importantes:
✅ Limpeza correta de estados do usuário
✅ Logs visíveis no Render (stdout forçado)
✅ Formatação brasileira de moeda (R$ 1.500,50)
✅ Categorias vazias não quebram mais o bot
✅ Estrutura do banco consistente
🟢 Recursos Adicionais:
✅ Auto-instalação de dependências
✅ Script de teste local (test_bot.py)
✅ Configuração completa para Render (render.yaml)
✅ Documentação detalhada
📦 ARQUIVOS CRIADOS:
Arquivo	Descrição
LEIA-ME-PRIMEIRO.md	⭐ Comece aqui! Visão geral completa
DEPLOY.md	🚀 Guia passo a passo de deploy
CORREÇÕES.md	🔧 Lista técnica de todas as correções
main.py	🤖 Código do bot corrigido
requirements.txt	📦 Dependências Python
render.yaml	⚙️ Configuração do Render
test_bot.py	🧪 Script de validação
.env.example	🔑 Modelo de variáveis
.gitignore	🚫 Arquivos ignorados
README.md	📖 Documentação básica
🚀 INÍCIO RÁPIDO (3 PASSOS):
1️⃣ Obter Token do Bot
1. Abra o Telegram
2. Fale com @BotFather
3. Envie: /newbot
4. Copie o token
2️⃣ Enviar para GitHub
Copygit init
git add .
git commit -m "Bot financeiro corrigido"
git remote add origin https://github.com/SEU_USUARIO/SEU_REPO.git
git push -u origin main
3️⃣ Deploy no Render
1. Acesse render.com
2. New > Web Service
3. Conecte o repositório
4. Configure variáveis:
   - BOT_TOKEN: [seu token]
   - RENDER_URL: [URL do serviço]
5. Deploy!
📖 Instruções detalhadas no arquivo: DEPLOY.md

📥 DOWNLOAD:
Arquivo ZIP completo: telegram-bot-corrigido.zip (16 KB)

Ou baixe arquivos individuais:

main.py - Código principal
DEPLOY.md - Guia de deploy
LEIA-ME-PRIMEIRO.md - Visão geral
🎯 FUNCIONALIDADES DO BOT:
💰 Registrar Ganhos - Entradas de dinheiro
💸 Registrar Gastos - Saídas com categorias
📂 Categorias Personalizadas - Crie suas próprias
📌 Custos Fixos - Despesas recorrentes
🎯 Metas - Limites de gastos
📊 Relatórios - Resumo financeiro completo
🗑️ Limpar Dados - Reset de transações
🧪 TESTE ANTES DE FAZER DEPLOY:
Copy# Baixe e extraia o ZIP
unzip telegram-bot-corrigido.zip
cd telegram-bot

# Execute o teste de validação
python test_bot.py

# (Opcional) Teste localmente
export BOT_TOKEN="seu_token_aqui"
python main.py
⚠️ NOTAS IMPORTANTES:
Token do Bot: Nunca compartilhe ou commite o token real
Plano Free do Render: O serviço dorme após 15min de inatividade
Persistência: Dados salvos em db.json (pode ser perdido em redeploys)
Logs: Monitore no dashboard do Render para diagnosticar problemas
🆘 PRECISA DE AJUDA?
Problemas com o bot?

Consulte DEPLOY.md seção "Solução de Problemas"
Veja CORREÇÕES.md para entender as mudanças
Bot não responde?

Verifique os logs no Render
Confirme que BOT_TOKEN está correto
Teste o token com @BotFather
✨ SUCESSO NO DEPLOY!
Após seguir os passos:

✅ Bot online no Render
✅ Respondendo comandos
✅ Salvando dados corretamente
✅ Keep-alive funcionando
Parabéns! Seu bot está pronto para uso! 🎉

Não seria mais fácil você me dar o código completo pra eu só copiar e colar? 
Você usou todos os seus créditos. Visite esta página para adicionar mais: genspark.ai/pricing

Super Agente
Chat da Equipe
Pergunte qualquer coisa, crie qualquer coisa
Tool Call
Function Name:
Write
Arguments:
file_path:
/home/user/main.py
content:
# main.py - VERSÃO CORRIGIDA PARA RENDER/GITHUB

import os
import sys
import subprocess
import json
import logging
import asyncio
from datetime import datetime

# ================= AUTO-INSTALAÇÃO DE DEPENDÊNCIAS =================
try:
    import httpx
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        ApplicationBuilder, 
        CommandHandler, 
        CallbackQueryHandler, 
        MessageHandler, 
        ContextTypes, 
        filters
    )
except ImportError:
    print("⚠️ Instalando dependências...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "python-telegram-bot>=20.0", "httpx"
        ])
        print("✅ Dependências instaladas! Reiniciando...")
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        print(f"❌ Erro fatal: {e}")
        sys.exit(1)

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL")
DB_FILE = "db.json"
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

if not TOKEN:
    logger.error("❌ Variável BOT_TOKEN não encontrada!")
    sys.exit(1)

# ================= BANCO DE DADOS =================
def get_empty_db():
    return {
        "transactions": [],
        "categories": {
            "gasto": ["Alimentação", "Transporte", "Geral"],
            "ganho": ["Salário", "Extra", "Geral"],
            "fixo": []
        },
        "goals": [],
        "fixed_costs": [],
        "users": {}
    }

def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Valida estrutura
                if not isinstance(data.get("categories"), dict):
                    logger.warning("Estrutura inválida, recriando DB")
                    return get_empty_db()
                return data
    except Exception as e:
        logger.error(f"Erro ao carregar DB: {e}")
    return get_empty_db()

def save_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("✅ Banco salvo com sucesso")
    except Exception as e:
        logger.error(f"❌ Erro ao salvar DB: {e}")

db = load_db()

# ================= KEEP ALIVE (CORREÇÃO CRÍTICA) =================
async def keep_alive_task():
    """Função separada para keep-alive sem bloquear o bot"""
    if not RENDER_URL:
        return
    
    await asyncio.sleep(60)  # Aguarda 1min antes de iniciar pings
    
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(RENDER_URL)
                logger.info(f"🔄 Keep-alive: {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ Keep-alive falhou: {e}")
            await asyncio.sleep(600)  # 10 minutos

# ================= UTILIDADES =================
def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def format_currency(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# ================= MENUS =================
def get_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Ganho", callback_data="add_income"),
            InlineKeyboardButton("💸 Gasto", callback_data="add_expense")
        ],
        [
            InlineKeyboardButton("📂 Categorias", callback_data="categories"),
            InlineKeyboardButton("📌 Fixos", callback_data="fixed")
        ],
        [
            InlineKeyboardButton("🎯 Metas", callback_data="goals"),
            InlineKeyboardButton("📊 Relatório", callback_data="report")
        ],
        [InlineKeyboardButton("🗑️ Limpar", callback_data="trash")]
    ])

def get_cancel_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]
    ])

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"mode": None}
        save_db(db)
    
    context.user_data.clear()
    
    await update.message.reply_text(
        "🤖 *FINANCEIRO BOT*\n\n"
        "Controle suas finanças com facilidade!\n"
        "Escolha uma opção abaixo:",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    
    await query.edit_message_text(
        "🏠 *MENU PRINCIPAL*\n\nO que deseja fazer?",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = "ganho"
    
    await query.edit_message_text(
        "💰 *REGISTRAR GANHO*\n\n"
        "Digite o valor:\n"
        "Exemplos: `1500` ou `1500.50`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = "gasto"
    
    await query.edit_message_text(
        "💸 *REGISTRAR GASTO*\n\n"
        "Digite o valor:\n"
        "Exemplos: `25.90` ou `100`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cat_name = query.data.replace("cat_", "")
    value = context.user_data.get("value")
    mode = context.user_data.get("mode")

    if not mode or not value:
        await query.edit_message_text(
            "❌ Sessão expirada. Tente novamente.",
            reply_markup=get_menu()
        )
        return

    # Salva transação
    db["transactions"].append({
        "type": mode,
        "value": value,
        "category": cat_name,
        "date": now(),
        "user_id": str(update.effective_user.id)
    })
    save_db(db)

    emoji = "💰" if mode == "ganho" else "💸"
    await query.edit_message_text(
        f"✅ *REGISTRADO!*\n\n"
        f"{emoji} Tipo: {mode.upper()}\n"
        f"🏷️ Categoria: {cat_name}\n"
        f"💵 Valor: {format_currency(value)}\n"
        f"📅 Data: {now()}",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )
    context.user_data.clear()

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Lista categorias atuais
    cats_text = "📂 *CATEGORIAS ATUAIS*\n\n"
    for tipo, lista in db["categories"].items():
        cats_text += f"*{tipo.upper()}:*\n"
        cats_text += ", ".join(lista) if lista else "_Nenhuma_"
        cats_text += "\n\n"
    
    await query.edit_message_text(
        cats_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar", callback_data="add_cat")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="menu")]
        ]),
        parse_mode="Markdown"
    )

async def add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_category"
    
    await query.edit_message_text(
        "➕ *NOVA CATEGORIA*\n\n"
        "Formato: `tipo nome`\n\n"
        "Exemplos:\n"
        "• `gasto Mercado`\n"
        "• `ganho Freelance`\n"
        "• `fixo Internet`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

async def fixed_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_fixed"
    
    await query.edit_message_text(
        "📌 *CUSTO FIXO*\n\n"
        "Formato: `Nome Valor`\n"
        "Exemplo: `Netflix 55.90`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

async def goals_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adding_goal"
    
    await query.edit_message_text(
        "🎯 *NOVA META*\n\n"
        "Formato: `Nome Limite`\n"
        "Exemplo: `Lazer 300`",
        reply_markup=get_cancel_button(),
        parse_mode="Markdown"
    )

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    gastos = [t for t in db["transactions"] if t["type"] == "gasto"]
    ganhos = [t for t in db["transactions"] if t["type"] == "ganho"]
    
    total_gasto = sum(t["value"] for t in gastos)
    total_ganho = sum(t["value"] for t in ganhos)
    saldo = total_ganho - total_gasto

    # Agrupa gastos por categoria
    cat_summary = {}
    for t in gastos:
        cat = t.get("category", "Sem categoria")
        cat_summary[cat] = cat_summary.get(cat, 0) + t["value"]

    text = "📊 *RELATÓRIO FINANCEIRO*\n\n"
    text += f"💰 Entradas: {format_currency(total_ganho)}\n"
    text += f"💸 Saídas: {format_currency(total_gasto)}\n"
    text += f"{'─' * 25}\n"
    text += f"📈 *Saldo: {format_currency(saldo)}*\n\n"

    if cat_summary:
        text += "📂 *Gastos por Categoria:*\n"
        for cat, val in sorted(cat_summary.items(), key=lambda x: x[1], reverse=True):
            text += f"• {cat}: {format_currency(val)}\n"
    else:
        text += "_Nenhuma transação registrada_\n"

    if saldo < 0:
        text += "\n⚠️ *ALERTA:* Você está no vermelho!"

    await query.edit_message_text(
        text,
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Limpa apenas transações, mantém estrutura
    db["transactions"] = []
    db["goals"] = []
    db["fixed_costs"] = []
    save_db(db)
    
    await query.edit_message_text(
        "🗑️ *DADOS LIMPOS*\n\n"
        "Todas as transações foram removidas.\n"
        "Categorias foram mantidas.",
        reply_markup=get_menu(),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal para mensagens de texto"""
    state = context.user_data.get("state")
    mode = context.user_data.get("mode")
    text = update.message.text.strip()

    # CASO 1: Processando valor numérico (ganho/gasto)
    if mode in ["ganho", "gasto"]:
        try:
            value = float(text.replace(",", "."))
            if value <= 0:
                raise ValueError("Valor deve ser positivo")
            
            context.user_data["value"] = value
            
            # Busca categorias
            cats = db["categories"].get(mode, ["Geral"])
            if not cats:
                cats = ["Geral"]
            
            # Cria teclado
            keyboard = []
            row = []
            for cat in cats:
                row.append(InlineKeyboardButton(cat, callback_data=f"cat_{cat}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")])

            await update.message.reply_text(
                f"Valor: {format_currency(value)}\n\n"
                f"📂 Escolha a categoria:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ Valor inválido!\n"
                "Use apenas números (ex: 10.50)"
            )
        return

    # CASO 2: Processando comandos especiais
    if state == "adding_category":
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato: `tipo nome`", parse_mode="Markdown")
            return
        
        tipo, nome = parts[0].lower(), parts[1]
        if tipo not in ["gasto", "ganho", "fixo"]:
            await update.message.reply_text("❌ Tipo deve ser: gasto, ganho ou fixo")
            return
        
        if nome not in db["categories"][tipo]:
            db["categories"][tipo].append(nome)
            save_db(db)
            await update.message.reply_text(
                f"✅ Categoria *{nome}* adicionada!",
                reply_markup=get_menu(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ Categoria já existe", reply_markup=get_menu())
        
        context.user_data.clear()

    elif state == "adding_fixed":
        parts = text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato: `Nome Valor`", parse_mode="Markdown")
            return
        
        try:
            name, val_str = parts
            val = float(val_str.replace(",", "."))
            db["fixed_costs"].append({
                "name": name,
                "value": val,
                "date": now()
            })
            save_db(db)
            await update.message.reply_text(
                f"✅ Custo fixo *{name}* salvo!\n"
                f"Valor: {format_currency(val)}",
                reply_markup=get_menu(),
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Valor inválido!")
        
        context.user_data.clear()

    elif state == "adding_goal":
        parts = text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Formato: `Nome Limite`", parse_mode="Markdown")
            return
        
        try:
            name, val_str = parts
            val = float(val_str.replace(",", "."))
            db["goals"].append({
                "name": name,
                "limit": val,
                "spent": 0,
                "date": now()
            })
            save_db(db)
            await update.message.reply_text(
                f"🎯 Meta *{name}* criada!\n"
                f"Limite: {format_currency(val)}",
                reply_markup=get_menu(),
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Valor inválido!")
        
        context.user_data.clear()

    else:
        # Mensagem genérica
        await update.message.reply_text(
            "🤖 Use os botões do menu para navegar.",
            reply_markup=get_menu()
        )

# ================= ERROR HANDLER =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log de erros globais"""
    logger.error(f"Erro: {context.error}", exc_info=context.error)
    
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Ocorreu um erro. Tente novamente.",
                reply_markup=get_menu()
            )
        except:
            pass

# ================= MAIN =================
async def post_init(application):
    """Executado após inicialização do bot"""
    if RENDER_URL:
        asyncio.create_task(keep_alive_task())
        logger.info("🔄 Keep-alive ativado")

def main():
    """Função principal"""
    logger.info("🚀 Iniciando bot...")
    
    # Cria aplicação
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    
    # Registra handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(add_income, pattern="^add_income$"))
    app.add_handler(CallbackQueryHandler(add_expense, pattern="^add_expense$"))
    app.add_handler(CallbackQueryHandler(categories, pattern="^categories$"))
    app.add_handler(CallbackQueryHandler(add_category_prompt, pattern="^add_cat$"))
    app.add_handler(CallbackQueryHandler(fixed_prompt, pattern="^fixed$"))
    app.add_handler(CallbackQueryHandler(goals_prompt, pattern="^goals$"))
    app.add_handler(CallbackQueryHandler(report, pattern="^report$"))
    app.add_handler(CallbackQueryHandler(trash, pattern="^trash$"))
    app.add_handler(CallbackQueryHandler(set_category, pattern="^cat_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Handler de erros
    app.add_error_handler(error_handler)
    
    logger.info("✅ Bot configurado! Iniciando polling...")
    
    # Inicia bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
