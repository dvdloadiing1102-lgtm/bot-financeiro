import os
import json
import logging
import uuid
import io
import csv
import ast
import random
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import google.generativeai as genai
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip().isdigit()]
DB_FILE = "finance_v24_control.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= IA AUTO-CONFIG =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        chosen = next((m for m in models if 'flash' in m), next((m for m in models if 'gemini-pro' in m), None))
        if chosen: model_ai = genai.GenerativeModel(chosen)
    except: pass

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [], 
        "categories": {
            "ganho": ["Salário", "Extra", "Investimento"], 
            "gasto": ["Alimentação", "Transporte", "Lazer", "Mercado", "Casa", "Saúde", "Compras", "Assinaturas"]
        }, 
        "wallets": ["Nubank", "Itaú", "Dinheiro", "Inter", "VR/VA", "Crédito"],
        "budgets": {"Alimentação": 800, "Lazer": 300},
        "subscriptions": [],
        "shopping_list": [],
        "fixed": [], 
        "config": {"persona": "padrao", "panic_mode": False}
    }
    if not os.path.exists(DB_FILE): return default
    try:
        with open(DB_FILE, "r") as f: 
            data = json.load(f)
            for k in default: 
                if k not in data: data[k] = default[k]
            return data
    except: return default

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2)

db = load_db()

# ================= ESTADOS CONVERSA =================
(REG_TYPE, REG_VALUE, REG_WALLET, REG_CAT, REG_DESC, 
 NEW_CAT_TYPE, NEW_CAT_NAME, SHOP_VAL) = range(8)

# ================= LÓGICA GERAL =================
def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Acesso Negado."); return
        return await func(update, context, *args, **kwargs)
    return wrapped

def calc_stats():
    now = datetime.now(); mes = now.strftime("%m/%Y")
    ganhos = sum(t['value'] for t in db["transactions"] if t['type']=='ganho' and mes in t['date'])
    gastos = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and mes in t['date'])
    return (ganhos - gastos), ganhos, gastos

def get_persona_prompt():
    p = db["config"]["persona"]
    panic = db["config"]["panic_mode"]
    
    base = "Atue como consultor financeiro."
    
    if panic:
        return base + " MODO PÂNICO ATIVADO! O usuário está em crise. SE ELE TENTAR REGISTRAR LAZER, IFOOD, UBER OU COMPRAS FÚTEIS, RECUSE! Dê uma bronca e não registre. Só aceite Mercado, Farmácia e Contas. Seja agressivo."

    personas = {
        "padrao": "Seja profissional.",
        "julius": "Você é o Julius (Todo Mundo Odeia o Chris). Reclame do preço.",
        "primo": "Você é o Primo Rico. Fale de investimentos.",
        "mae": "Você é Mãe. Pergunte se ele comeu.",
        "zoeiro": "Seja sarcástico e zoeiro."
    }
    return base + " " + personas.get(p, personas["padrao"])

# ================= IA INTELIGENTE =================
@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message
    
    prompt = f"""
    {get_persona_prompt()}
    Analise: "{msg.text or 'FOTO'}".
    
    Se for tentativa de gasto fútil e PÂNICO estiver ativo: Responda apenas com texto de bronca e NÃO gere JSON.
    
    Se for financeiro válido, retorne JSON:
    {{"type": "gasto/ganho/transferencia", "value": float, "category": "string", "wallet": "string", "description": "string", "installments": 1}}
    
    Se não for financeiro, responda texto normal.
    """
    
    wait = await msg.reply_text("🧠...")
    try:
        content = [prompt]
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id)
            d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": d})
        
        resp = model_ai.generate_content(content)
        txt = resp.text.strip().replace("```json", "").replace("```", "")
        
        # Tenta extrair JSON (com correção de aspas simples)
        data = None
        if "{" in txt and "}" in txt:
            json_cand = txt[txt.find("{"):txt.rfind("}")+1]
            try: data = json.loads(json_cand)
            except: 
                try: data = ast.literal_eval(json_cand)
                except: pass

        if data:
            # Lógica de registro
            inst = data.get("installments", 1)
            val = float(data['value'])
            base_date = datetime.now()
            
            for i in range(inst):
                d_date = base_date + relativedelta(months=i)
                desc = data['description'] + (f" ({i+1}/{inst})" if inst > 1 else "")
                
                db["transactions"].append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "gasto" if data['type']=='transferencia' else data['type'],
                    "value": val / inst if inst > 1 else val,
                    "category": data['category'],
                    "wallet": data['wallet'],
                    "description": desc,
                    "date": d_date.strftime("%d/%m/%Y %H:%M"),
                    "user_id": msg.from_user.id
                })
            save_db(db)
            res = f"✅ **{data['category']}** | R$ {val:.2f}\n📝 {data['description']}"
            if inst > 1: res += f"\n📅 {inst}x parcelas"
            await wait.edit_text(res)
        else:
            # Apenas resposta (Bronca ou Conversa)
            await wait.edit_text(txt)
            
    except Exception as e:
        await wait.edit_text(f"Erro: {e}")

# ================= MENU PRINCIPAL =================
@restricted
async def start(update, context):
    context.user_data.clear()
    saldo, ganho, gasto = calc_stats()
    
    # Ícones Dinâmicos
    p_name = db["config"]["persona"].upper()
    panic_st = "🚨 ON" if db["config"]["panic_mode"] else "✅ OFF"
    
    kb = [
        [InlineKeyboardButton(f"🎭 {p_name}", callback_data="menu_persona"), InlineKeyboardButton(f"Pânico: {panic_st}", callback_data="toggle_panic")],
        [InlineKeyboardButton("📂 Categorias", callback_data="menu_cats"), InlineKeyboardButton("🗑️ Excluir Item", callback_data="menu_delete")],
        [InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop"), InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")],
        [InlineKeyboardButton("📝 Manual", callback_data="start_reg"), InlineKeyboardButton("📉 Relatórios", callback_data="menu_reports")],
        [InlineKeyboardButton("🔮 Vidente", callback_data="vidente"), InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]
    
    msg = (f"⚡ **FINANCEIRO V24 (CONTROL)** ⚡\n\n"
           f"💰 Saldo: **R$ {saldo:.2f}**\n"
           f"📈 Entrou: R$ {ganho:.2f} | 📉 Saiu: R$ {gasto:.2f}\n\n"
           f"💡 *IA e Botões Voltar ativos.*")
    
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ================= GERENCIAR CATEGORIAS (NOVO) =================
async def menu_cats(update, context):
    query = update.callback_query; await query.answer()
    kb = [
        [InlineKeyboardButton("➕ Nova Categoria", callback_data="cat_add")],
        [InlineKeyboardButton("❌ Excluir Categoria", callback_data="cat_del_menu")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="start")]
    ]
    await query.edit_message_text("📂 **Gerenciar Categorias:**", reply_markup=InlineKeyboardMarkup(kb))

# --- Adicionar Categoria ---
async def cat_add_start(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="new_cat_gasto"), InlineKeyboardButton("Ganho", callback_data="new_cat_ganho")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text("Essa categoria é de Gasto ou Ganho?", reply_markup=InlineKeyboardMarkup(kb))
    return NEW_CAT_TYPE

async def cat_add_type(update, context):
    query = update.callback_query; await query.answer()
    if query.data == "start": return await start(update, context)
    
    context.user_data["nc_type"] = query.data.replace("new_cat_", "")
    await query.edit_message_text("✍️ Digite o nome da nova categoria:")
    return NEW_CAT_NAME

async def cat_add_save(update, context):
    name = update.message.text
    tipo = context.user_data["nc_type"]
    if name not in db["categories"][tipo]:
        db["categories"][tipo].append(name)
        save_db(db)
        await update.message.reply_text(f"✅ Categoria '{name}' adicionada em {tipo}!")
    else:
        await update.message.reply_text("Essa categoria já existe.")
    return await start(update, context)

# --- Excluir Categoria ---
async def cat_del_menu(update, context):
    query = update.callback_query; await query.answer()
    kb = []
    # Lista todas as categorias com botão de apagar
    for tipo in ["gasto", "ganho"]:
        for c in db["categories"][tipo]:
            kb.append([InlineKeyboardButton(f"🗑️ {c} ({tipo})", callback_data=f"delcat_{tipo}_{c}")])
    
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_cats")])
    await query.edit_message_text("Selecione para excluir:", reply_markup=InlineKeyboardMarkup(kb))

async def cat_del_exec(update, context):
    query = update.callback_query; await query.answer()
    _, tipo, nome = query.data.split("_")
    
    if nome in db["categories"][tipo]:
        db["categories"][tipo].remove(nome)
        save_db(db)
        await query.edit_message_text(f"✅ Categoria '{nome}' removida!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_cats")]]))
    else:
        await query.edit_message_text("Erro ao remover.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_cats")]]))

# ================= EXCLUIR TRANSAÇÕES =================
async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    # Pega as últimas 5 transações
    last = db["transactions"][-5:]
    kb = []
    for t in reversed(last):
        btn_txt = f"❌ {t['date'][:5]} - R$ {t['value']} ({t['description']})"
        kb.append([InlineKeyboardButton(btn_txt, callback_data=f"kill_{t['id']}")])
    
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="start")])
    msg = "🗑️ **Excluir Transação Recente:**\n(Clique para apagar permanentemente)"
    if not last: msg = "Nenhuma transação para apagar."
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def delete_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    # Filtra mantendo apenas os que NÃO tem esse ID
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]
    save_db(db)
    await query.edit_message_text("✅ Item apagado com sucesso!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="start")]]))

# ================= MODO PÂNICO (FIX) =================
async def toggle_panic(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["panic_mode"] = not db["config"]["panic_mode"]
    save_db(db)
    status = "ATIVADO 🚨" if db["config"]["panic_mode"] else "DESATIVADO ✅"
    # Força a atualização do menu chamando start
    await start(update, context)

# ================= REGISTRO MANUAL =================
async def start_reg(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="reg_gasto"), InlineKeyboardButton("Ganho", callback_data="reg_ganho")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb))
    return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query
    if query.data == "start": return await start(update, context)
    context.user_data["t_t"] = query.data.split("_")[1]
    await query.edit_message_text("💰 Valor (ex: 25.00):")
    return REG_VALUE

async def reg_val(update, context):
    try:
        context.user_data["t_v"] = float(update.message.text.replace(',', '.'))
        # Seleção de Categoria Manual
        cats = db["categories"][context.user_data["t_t"]]
        kb = []
        for i in range(0, len(cats), 2):
            kb.append([InlineKeyboardButton(c, callback_data=f"selcat_{c}") for c in cats[i:i+2]])
        await update.message.reply_text("📂 Categoria:", reply_markup=InlineKeyboardMarkup(kb))
        return REG_CAT
    except: 
        await update.message.reply_text("Valor inválido.")
        return REG_VALUE

async def reg_cat(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["t_c"] = query.data.replace("selcat_", "")
    await query.edit_message_text("📝 Descrição (ou digite 'ok'):")
    return REG_DESC

async def reg_finish(update, context):
    desc = update.message.text
    if desc.lower() == 'ok': desc = context.user_data["t_c"]
    
    db["transactions"].append({
        "id": str(uuid.uuid4())[:8],
        "type": context.user_data["t_t"],
        "value": context.user_data["t_v"],
        "category": context.user_data["t_c"],
        "wallet": "Manual",
        "description": desc,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_db(db)
    await update.message.reply_text("✅ Salvo!")
    return await start(update, context)

async def cancel(update, context):
    await start(update, context)
    return ConversationHandler.END

# ================= OUTRAS FUNÇÕES (PERSONA, SHOP, REPORTS) =================
# Mantendo as funções da V23 mas adicionando botão Voltar em todas

async def menu_persona(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("😠 Julius", callback_data="set_julius"), InlineKeyboardButton("🥃 Primo", callback_data="set_primo")],
          [InlineKeyboardButton("👵 Mãe", callback_data="set_mae"), InlineKeyboardButton("🤡 Zoeiro", callback_data="set_zoeiro")],
          [InlineKeyboardButton("🤖 Padrão", callback_data="set_padrao")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text("Escolha a Personalidade:", reply_markup=InlineKeyboardMarkup(kb))

async def set_persona(update, context):
    query = update.callback_query
    db["config"]["persona"] = query.data.replace("set_", "")
    save_db(db)
    await start(update, context)

async def menu_shop(update, context):
    query = update.callback_query; await query.answer()
    lista = db["shopping_list"]
    txt = "**🛒 Lista de Compras:**\n" + ("\n".join([f"▫️ {i}" for i in lista]) if lista else "*(Vazia)*")
    kb = [[InlineKeyboardButton("✅ Finalizar", callback_data="shop_finish"), InlineKeyboardButton("🗑️ Limpar", callback_data="shop_clear")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_shop_item(update, context):
    item = " ".join(context.args)
    if item: db["shopping_list"].append(item); save_db(db); await update.message.reply_text(f"➕ {item}")

async def shop_finish(update, context):
    query = update.callback_query; await query.answer()
    if not db["shopping_list"]: return await query.message.reply_text("Lista vazia!")
    await query.edit_message_text("💰 Valor total da compra?")
    return SHOP_VAL

async def shop_save(update, context):
    try:
        val = float(update.message.text.replace(',', '.'))
        desc = "Mercado: " + ", ".join(db["shopping_list"])
        db["transactions"].append({"id": str(uuid.uuid4())[:8], "type": "gasto", "value": val, "category": "Mercado", "wallet": "Nubank", "description": desc[:100], "date": datetime.now().strftime("%d/%m/%Y %H:%M")})
        db["shopping_list"] = []; save_db(db)
        await update.message.reply_text("✅ Salvo!"); return await start(update, context)
    except: await update.message.reply_text("Erro valor."); return SHOP_VAL

async def shop_clear(update, context):
    db["shopping_list"] = []; save_db(db); await start(update, context)

async def menu_subs(update, context):
    query = update.callback_query; await query.answer()
    txt = "**🔔 Assinaturas:**\n"
    for s in db["subscriptions"]: txt += f"📺 {s['name']}: R$ {s['val']}\n"
    txt += "\nAdicionar: `/sub Netflix 55.90`"
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="start")]]), parse_mode="Markdown")

async def add_sub(update, context):
    try:
        val = float(context.args[-1].replace(',', '.'))
        name = " ".join(context.args[:-1])
        db["subscriptions"].append({"name": name, "val": val}); save_db(db)
        await update.message.reply_text("✅ Salvo!")
    except: pass

async def vidente(update, context):
    query = update.callback_query; await query.answer()
    now = datetime.now()
    mes = now.strftime("%m/%Y")
    gasto = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and mes in t['date'])
    
    dia = now.day
    ultimo = (now.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
    prev = gasto + ((gasto/dia) * (ultimo - dia)) if dia > 0 else 0
    
    msg = f"🔮 Previsão de Fim de Mês: **R$ {prev:.2f}**"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="start")]]), parse_mode="Markdown")

async def menu_reports(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📊 Pizza", callback_data="chart_pie"), InlineKeyboardButton("📉 Evolução", callback_data="chart_evo")],
          [InlineKeyboardButton("📄 PDF", callback_data="export_pdf"), InlineKeyboardButton("🔙 Voltar", callback_data="start")]]
    await query.edit_message_text("📊 Relatórios:", reply_markup=InlineKeyboardMarkup(kb))

# Funções gráficas/PDF (mantidas simplificadas)
async def export_pdf(update, context):
    query = update.callback_query; await query.answer()
    path = "/tmp/rel.pdf" if os.name != 'nt' else "rel.pdf"
    c = canvas.Canvas(path, pagesize=letter); c.drawString(100, 750, "Extrato V24"); c.save()
    with open(path, 'rb') as f: await query.message.reply_document(f)

async def backup_db(update, context):
    query = update.callback_query; await query.answer()
    with open(DB_FILE, 'rb') as f: await query.message.reply_document(f)

async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    mes = datetime.now().strftime("%m/%Y")
    cats = {}
    for t in db["transactions"]:
        if t['type']=='gasto' and mes in t['date']: cats[t['category']] = cats.get(t['category'], 0) + t['value']
    if not cats: await query.message.reply_text("Sem dados."); return
    plt.figure(figsize=(6,4)); plt.pie(cats.values(), labels=cats.keys(), autopct='%1.1f%%'); plt.title(f"Gastos {mes}")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)

async def chart_evo(update, context):
    query = update.callback_query; await query.answer()
    dados, labels = [], []
    hoje = datetime.now()
    for i in range(5, -1, -1):
        mes = (hoje - relativedelta(months=i)).strftime("%m/%Y")
        val = sum(t['value'] for t in db["transactions"] if t['type']=='gasto' and mes in t['date'])
        dados.append(val); labels.append(mes[:2])
    plt.figure(figsize=(6, 4)); plt.plot(labels, dados, marker='o', color='purple'); plt.grid(True)
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    if not TOKEN: print("SEM TOKEN")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Comandos e Start
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("add", add_shop_item))
        app.add_handler(CommandHandler("sub", add_sub))
        
        # Conversa Categoria Nova
        cat_h = ConversationHandler(
            entry_points=[CallbackQueryHandler(cat_add_start, pattern="^cat_add$")],
            states={
                NEW_CAT_TYPE: [CallbackQueryHandler(cat_add_type)],
                NEW_CAT_NAME: [MessageHandler(filters.TEXT, cat_add_save)]
            }, fallbacks=[CallbackQueryHandler(cancel, pattern="^start")]
        )
        app.add_handler(cat_h)

        # Conversa Compra
        shop_h = ConversationHandler(
            entry_points=[CallbackQueryHandler(shop_finish, pattern="shop_finish")],
            states={SHOP_VAL: [MessageHandler(filters.TEXT, shop_save)]},
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        app.add_handler(shop_h)
        
        # Conversa Manual
        reg_h = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_reg, pattern="start_reg")],
            states={
                REG_TYPE:[CallbackQueryHandler(reg_type)], 
                REG_VALUE:[MessageHandler(filters.TEXT, reg_val)], 
                REG_CAT:[CallbackQueryHandler(reg_cat)],
                REG_DESC:[MessageHandler(filters.TEXT, reg_finish)]
            },
            fallbacks=[CallbackQueryHandler(cancel, pattern="start")]
        )
        app.add_handler(reg_h)

        # Callbacks Gerais
        app.add_handler(CallbackQueryHandler(menu_cats, pattern="^menu_cats"))
        app.add_handler(CallbackQueryHandler(cat_del_menu, pattern="^cat_del_menu"))
        app.add_handler(CallbackQueryHandler(cat_del_exec, pattern="^delcat_"))
        app.add_handler(CallbackQueryHandler(menu_delete, pattern="^menu_delete"))
        app.add_handler(CallbackQueryHandler(delete_item, pattern="^kill_"))
        
        # Callbacks Menus Extras
        extra_patterns = ["menu_shop", "shop_clear", "menu_subs", "menu_persona", "set_", "toggle_panic", "vidente", "menu_reports", "export_pdf", "chart_", "backup"]
        for p in extra_patterns:
            # Lambda mágica para rotear corretamente
            app.add_handler(CallbackQueryHandler(
                lambda u,c: eval(u.callback_query.data.split('_')[0] if 'set' not in u.callback_query.data and 'delcat' not in u.callback_query.data else 'set_persona')(u,c) if 'set' in u.callback_query.data else eval(u.callback_query.data)(u,c),
                pattern=f"^{p}"
            ))
            # Obs: Para evitar erros com o eval em patterns complexos, registrei os principais (cat, delete) explicitamente acima.
            # O loop abaixo pega o resto simples (menus de relatorio, shop, persona).
            
        # IA handler
        app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, restricted(smart_entry)))
        
        print("🤖 V24 CONTROL RODANDO!")
        app.run_polling(drop_pending_updates=True)
