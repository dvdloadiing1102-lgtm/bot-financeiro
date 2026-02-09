import os
import json
import logging
import uuid
import io
import csv
import ast
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

# ================= CONFIGURAÇÃO =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip().isdigit()]
DB_FILE = "finance_v26_audio.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ================= IA =================
model_ai = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        # Tenta pegar o modelo Flash (melhor para audio) ou Pro
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
(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, 
 CAT_ADD_TYPE, CAT_ADD_NAME, SHOP_VAL) = range(7)

# ================= HELPERS =================
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

# ================= MENU PRINCIPAL =================
@restricted
async def start_menu(update, context):
    context.user_data.clear()
    saldo, ganho, gasto = calc_stats()
    
    p_name = db["config"]["persona"].upper()
    panic_st = "🚨 ON" if db["config"]["panic_mode"] else "✅ OFF"
    
    kb = [
        [InlineKeyboardButton(f"🎭 Persona: {p_name}", callback_data="menu_persona"), InlineKeyboardButton(f"Pânico: {panic_st}", callback_data="toggle_panic")],
        [InlineKeyboardButton("📝 Novo Registro", callback_data="start_reg"), InlineKeyboardButton("📂 Categorias", callback_data="menu_cats")],
        [InlineKeyboardButton("🛒 Mercado", callback_data="menu_shop"), InlineKeyboardButton("🔔 Assinaturas", callback_data="menu_subs")],
        [InlineKeyboardButton("📊 Relatórios/Gráficos", callback_data="menu_reports"), InlineKeyboardButton("🗑️ Excluir Item", callback_data="menu_delete")],
        [InlineKeyboardButton("🔮 Vidente", callback_data="vidente"), InlineKeyboardButton("💾 Backup", callback_data="backup")]
    ]
    
    msg = (f"⚡ **FINANCEIRO V26 (AUDIO)** ⚡\n\n"
           f"💰 Saldo: **R$ {saldo:.2f}**\n"
           f"📈 Entrou: R$ {ganho:.2f}\n📉 Saiu: R$ {gasto:.2f}\n\n"
           f"🎤 **Dica:** Pode me mandar áudio!")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

async def back_to_main(update, context):
    if update.callback_query: await update.callback_query.answer()
    return await start_menu(update, context)

# ================= IA (TEXTO + FOTO + ÁUDIO) =================
@restricted
async def smart_entry(update, context):
    if not model_ai: await update.message.reply_text("⚠️ IA Offline."); return
    msg = update.message
    
    # 1. Pânico Check
    if db["config"]["panic_mode"] and msg.text:
        bad = ["lazer", "ifood", "uber", "jogo", "cerveja", "bar", "pizza", "mc", "burger"]
        if any(x in msg.text.lower() for x in bad):
            await msg.reply_text("🚨 **PÂNICO:** Gasto bloqueado! Vá para casa."); return

    wait = await msg.reply_text("🧠 Processando...")
    
    try:
        content = []
        
        # 2. Configura o Prompt
        prompt_txt = f"""
        Atue como {db['config']['persona']}.
        Analise o áudio, texto ou imagem.
        Retorne JSON: {{"type": "gasto/ganho", "value": float, "category": "string", "wallet": "string", "description": "string"}}
        Se não for financeiro, responda texto.
        """
        content.append(prompt_txt)
        
        # 3. Processa Anexos (Foto ou Áudio)
        file_path = None
        if msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id)
            d = await f.download_as_bytearray()
            content.append({"mime_type": "image/jpeg", "data": d})
            
        elif msg.voice or msg.audio:
            # Baixa o áudio
            file_id = (msg.voice or msg.audio).file_id
            f = await context.bot.get_file(file_id)
            file_path = f"audio_{uuid.uuid4()}.ogg"
            await f.download_to_drive(file_path)
            
            # Upload para o Gemini (necessário para arquivos de media)
            uploaded = genai.upload_file(file_path)
            content.append(uploaded)
            content.append("Transcreva e analise este áudio financeiro.")

        else:
            # Apenas texto
            content.append(f"Input: {msg.text}")

        # 4. Chama a IA
        resp = model_ai.generate_content(content)
        txt = resp.text.strip().replace("```json", "").replace("```", "")
        
        # Limpeza do arquivo de áudio temporário
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        
        # 5. Tenta ler o JSON
        data = None
        if "{" in txt:
            try: data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
            except: 
                try: data = ast.literal_eval(txt[txt.find("{"):txt.rfind("}")+1])
                except: pass
        
        if data:
            db["transactions"].append({
                "id": str(uuid.uuid4())[:8],
                "type": data['type'], "value": float(data['value']), "category": data['category'],
                "wallet": data.get('wallet', 'Manual'), "description": data['description'],
                "date": datetime.now().strftime("%d/%m/%Y %H:%M")
            })
            save_db(db)
            await wait.edit_text(f"✅ **Áudio/Texto Processado:**\n{data['category']} - R$ {data['value']}\n📝 {data['description']}")
        else:
            await wait.edit_text(txt)
            
    except Exception as e:
        await wait.edit_text(f"Erro IA: {e}")

# ================= RESTO DAS FUNÇÕES (MANUAIS) =================
# (Mantendo exatamente o que funcionava na V25)

async def reg_start(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="reg_gasto"), InlineKeyboardButton("Ganho", callback_data="reg_ganho")],
          [InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text("Selecione o tipo:", reply_markup=InlineKeyboardMarkup(kb)); return REG_TYPE

async def reg_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["type"] = query.data.replace("reg_", "")
    kb = [[InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text(f"💰 Valor do {context.user_data['type']}:", reply_markup=InlineKeyboardMarkup(kb)); return REG_VALUE

async def reg_value_save(update, context):
    try:
        val = float(update.message.text.replace(',', '.'))
        context.user_data["value"] = val
        cats = db["categories"][context.user_data["type"]]
        kb = []
        for i in range(0, len(cats), 2): kb.append([InlineKeyboardButton(c, callback_data=f"selcat_{c}") for c in cats[i:i+2]])
        kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="back_main")])
        await update.message.reply_text("📂 Categoria:", reply_markup=InlineKeyboardMarkup(kb)); return REG_CAT
    except: await update.message.reply_text("❌ Número inválido."); return REG_VALUE

async def reg_cat_save(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["cat"] = query.data.replace("selcat_", "")
    kb = [[InlineKeyboardButton("Pular Descrição", callback_data="skip_desc")], [InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text("📝 Descrição:", reply_markup=InlineKeyboardMarkup(kb)); return REG_DESC

async def reg_finish(update, context):
    desc = update.message.text if update.message else "Manual"
    if update.callback_query: await update.callback_query.answer(); desc = context.user_data["cat"]
    db["transactions"].append({"id": str(uuid.uuid4())[:8], "type": context.user_data["type"], "value": context.user_data["value"], "category": context.user_data["cat"], "wallet": "Manual", "description": desc, "date": datetime.now().strftime("%d/%m/%Y %H:%M")})
    save_db(db)
    msg = update.message or update.callback_query.message
    await msg.reply_text("✅ Salvo!"); return await start_menu(update, context)

# Categorias
async def menu_cats(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("➕ Criar", callback_data="cat_add_start"), InlineKeyboardButton("❌ Apagar", callback_data="cat_del_list")], [InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text("📂 Categorias:", reply_markup=InlineKeyboardMarkup(kb))
async def cat_add_start(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Gasto", callback_data="newcat_gasto"), InlineKeyboardButton("Ganho", callback_data="newcat_ganho")], [InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(kb)); return CAT_ADD_TYPE
async def cat_add_type(update, context):
    query = update.callback_query; await query.answer()
    context.user_data["nc_type"] = query.data.replace("newcat_", "")
    await query.edit_message_text("Nome:"); return CAT_ADD_NAME
async def cat_add_save(update, context):
    name = update.message.text; tipo = context.user_data["nc_type"]
    if name not in db["categories"][tipo]: db["categories"][tipo].append(name); save_db(db); await update.message.reply_text(f"✅ '{name}' Criada!")
    else: await update.message.reply_text("Já existe.")
    return await start_menu(update, context)
async def cat_del_list(update, context):
    query = update.callback_query; await query.answer()
    kb = []
    for t in ["gasto","ganho"]:
        for c in db["categories"][t]: kb.append([InlineKeyboardButton(f"🗑️ {c}", callback_data=f"delcat_{t}_{c}")])
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="back_main")])
    await query.edit_message_text("Apagar:", reply_markup=InlineKeyboardMarkup(kb))
async def cat_del_exec(update, context):
    query = update.callback_query; await query.answer()
    _, t, n = query.data.split("_"); 
    if n in db["categories"][t]: db["categories"][t].remove(n); save_db(db)
    await query.edit_message_text(f"✅ '{n}' apagada!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]))

# Deletar Item
async def menu_delete(update, context):
    query = update.callback_query; await query.answer()
    last = db["transactions"][-5:]
    kb = []
    for t in reversed(last): kb.append([InlineKeyboardButton(f"❌ {t['value']} - {t['description']}", callback_data=f"kill_{t['id']}")])
    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data="back_main")])
    await query.edit_message_text("🗑️ Apagar Recente:", reply_markup=InlineKeyboardMarkup(kb))
async def kill_item(update, context):
    query = update.callback_query; await query.answer()
    tid = query.data.replace("kill_", "")
    db["transactions"] = [t for t in db["transactions"] if t['id'] != tid]; save_db(db)
    await query.edit_message_text("✅ Apagado!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]))

# Extras
async def toggle_panic(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["panic_mode"] = not db["config"]["panic_mode"]; save_db(db)
    await start_menu(update, context)
async def menu_persona(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("Julius", callback_data="set_julius"), InlineKeyboardButton("Primo", callback_data="set_primo")],
          [InlineKeyboardButton("Mãe", callback_data="set_mae"), InlineKeyboardButton("Zoeiro", callback_data="set_zoeiro")],
          [InlineKeyboardButton("Padrão", callback_data="set_padrao"), InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text("🎭 Persona:", reply_markup=InlineKeyboardMarkup(kb))
async def set_persona(update, context):
    query = update.callback_query; await query.answer()
    db["config"]["persona"] = query.data.replace("set_", ""); save_db(db); await start_menu(update, context)
async def vidente(update, context):
    query = update.callback_query; await query.answer()
    _, _, gasto = calc_stats(); now = datetime.now(); dia = now.day; ultimo = 30
    prev = gasto + ((gasto/dia) * (ultimo - dia)) if dia > 0 else 0
    await query.edit_message_text(f"🔮 Previsão Fim Mês: **R$ {prev:.2f}**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]), parse_mode="Markdown")
async def menu_reports(update, context):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📄 PDF", callback_data="export_pdf"), InlineKeyboardButton("📊 Gráfico", callback_data="chart_pie")], [InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]
    await query.edit_message_text("Relatórios:", reply_markup=InlineKeyboardMarkup(kb))
async def export_pdf(update, context):
    query = update.callback_query; await query.answer()
    c = canvas.Canvas("rel.pdf", pagesize=letter); c.drawString(100,750,"Extrato V26"); c.save()
    with open("rel.pdf", "rb") as f: await query.message.reply_document(f)
async def chart_pie(update, context):
    query = update.callback_query; await query.answer()
    cats = {}
    for t in db["transactions"]:
        if t['type']=='gasto': cats[t['category']] = cats.get(t['category'], 0) + t['value']
    if not cats: await query.message.reply_text("Sem dados."); return
    plt.figure(figsize=(6,4)); plt.pie(cats.values(), labels=cats.keys(), autopct='%1.1f%%'); buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    await query.message.reply_photo(buf)
async def backup(update, context):
    query = update.callback_query; await query.answer()
    with open(DB_FILE, "rb") as f: await query.message.reply_document(f)

# Placeholders
async def menu_shop(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("🛒 Lista (Use áudio pra adicionar)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]))
async def menu_subs(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("🔔 Assinaturas (Em breve)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="back_main")]]))

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Conversas
    reg_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(reg_start, pattern="^start_reg$")],
        states={
            REG_TYPE: [CallbackQueryHandler(reg_type, pattern="^reg_"), CallbackQueryHandler(back_to_main, pattern="^back_main$")],
            REG_VALUE: [MessageHandler(filters.TEXT, reg_value_save), CallbackQueryHandler(back_to_main, pattern="^back_main$")],
            REG_CAT: [CallbackQueryHandler(reg_cat_save, pattern="^selcat_"), CallbackQueryHandler(back_to_main, pattern="^back_main$")],
            REG_DESC: [MessageHandler(filters.TEXT, reg_finish), CallbackQueryHandler(reg_finish, pattern="^skip_desc$"), CallbackQueryHandler(back_to_main, pattern="^back_main$")]
        }, fallbacks=[CallbackQueryHandler(back_to_main, pattern="^back_main$")]
    )
    
    cat_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(cat_add_start, pattern="^cat_add_start$")],
        states={
            CAT_ADD_TYPE: [CallbackQueryHandler(cat_add_type, pattern="^newcat_"), CallbackQueryHandler(back_to_main, pattern="^back_main$")],
            CAT_ADD_NAME: [MessageHandler(filters.TEXT, cat_add_save), CallbackQueryHandler(back_to_main, pattern="^back_main$")]
        }, fallbacks=[CallbackQueryHandler(back_to_main, pattern="^back_main$")]
    )

    app.add_handler(CommandHandler("start", start_menu))
    app.add_handler(reg_h)
    app.add_handler(cat_h)
    
    # Callbacks
    callbacks = [
        ("menu_cats", menu_cats), ("cat_del_list", cat_del_list), ("delcat_", cat_del_exec),
        ("menu_delete", menu_delete), ("kill_", kill_item), ("toggle_panic", toggle_panic),
        ("menu_persona", menu_persona), ("set_", set_persona), ("menu_reports", menu_reports),
        ("export_pdf", export_pdf), ("chart_", chart_pie), ("vidente", vidente), ("backup", backup),
        ("menu_shop", menu_shop), ("menu_subs", menu_subs), ("back_main", back_to_main)
    ]
    for p, f in callbacks: app.add_handler(CallbackQueryHandler(f, pattern=f"^{p}"))
    
    # IA (Agora com VOICE e AUDIO)
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO, restricted(smart_entry)))
    
    print("✅ Bot V26 (AUDIO ENABLED) Rodando!")
    app.run_polling(drop_pending_updates=True)
