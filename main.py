import os
import sys
import subprocess
import logging
import threading
import json
import uuid
import time
import io
import math
import random
import requests
from datetime import datetime, timedelta

# ================= AUTO-CORREÇÃO DE PACOTES =================
try:
    import google.generativeai as genai
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "google-generativeai"])
    import google.generativeai as genai

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
import warnings
warnings.filterwarnings("ignore")

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ALLOWED_USERS", "0").split(",")[0] if os.getenv("ALLOWED_USERS") else 0)
DB_FILE = "finance_v95.json"

(REG_TYPE, REG_VALUE, REG_CAT, REG_DESC, CAT_ADD_TYPE, CAT_ADD_NAME, DEBT_NAME, DEBT_VAL) = range(8)

# ================= IA SETUP FIX DEFINITIVO =================
model_ai = None

if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)

        available_models = []
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                available_models.append(m.name)

        print("📡 Modelos disponíveis:", available_models)

        priority = [
            "models/gemini-1.0-pro",
            "models/gemini-pro",
            "models/gemini-1.5-flash",
            "models/gemini-1.5-pro"
        ]

        selected = None
        for p in priority:
            if p in available_models:
                selected = p
                break

        if selected:
            model_ai = genai.GenerativeModel(selected)
            print(f"✅ IA Conectada: {selected}")
        else:
            print("⚠️ Nenhum modelo compatível encontrado.")
            model_ai = None

    except Exception as e:
        print("❌ Erro ao iniciar IA:", e)
        model_ai = None

# ================= BANCO DE DADOS =================
def load_db():
    default = {
        "transactions": [],
        "shopping_list": [],
        "debts_v2": {},
        "categories": {
            "ganho": ["Salário", "Extra"],
            "gasto": ["Alimentação", "Transporte", "Lazer", "Casa"]
        },
        "vip_users": {},
        "config": {"panic_mode": False}
    }
    if not os.path.exists(DB_FILE):
        return default
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return default

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

db = load_db()

# ================= UTIL =================
def get_now():
    return datetime.utcnow() - timedelta(hours=3)

def calc_stats():
    gan = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'ganho')
    gas = sum(t['value'] for t in db["transactions"] if str(t['type']).lower() == 'gasto')
    return gan - gas, gas

def is_vip(user_id):
    if user_id == ADMIN_ID:
        return True, "👑 ADMIN"
    u = db["vip_users"].get(str(user_id))
    if u and datetime.strptime(u, "%Y-%m-%d") > get_now():
        return True, "✅ VIP"
    return False, "❌ Bloqueado"

def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        if not is_vip(update.effective_user.id)[0]:
            await update.message.reply_text("🚫 VIP Necessário.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def check_reminders(context):
    now_str = get_now().strftime("%Y-%m-%d %H:%M")
    if "reminders" in db:
        for rem in db["reminders"]:
            if rem["time"] == now_str:
                try:
                    await context.bot.send_message(
                        chat_id=rem["chat_id"],
                        text=f"⏰ LEMBRETE!\n{rem['text']}"
                    )
                except:
                    pass

# ================= IA HANDLER =================
@restricted
async def smart_entry(update, context):
    if not model_ai:
        await update.message.reply_text("⚠️ IA Offline.")
        return

    msg = update.message
    wait = await msg.reply_text("🧠 Processando...")
    now = get_now()

    try:
        prompt = """
Responda APENAS em JSON válido.

- comprar leite → {"type":"mercado","item":"leite"}
- gastei 50 em lanche → {"type":"gasto","val":50,"cat":"Lazer"}
- ganhei 1000 salário → {"type":"ganho","val":1000,"cat":"Salário"}
- conversa normal → {"type":"conversa","msg":"resposta"}
"""

        resp = model_ai.generate_content([prompt, msg.text])
        text = resp.text.strip()

        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1:
            await wait.edit_text("🤖 Não entendi.")
            return

        data = json.loads(text[start:end+1])

        if data.get("type") == "mercado":
            db["shopping_list"].append(data["item"])
            save_db(db)
            await wait.edit_text(f"🛒 Adicionado: {data['item']}")
            return

        if data.get("type") in ["gasto", "ganho"]:
            db["transactions"].append({
                "id": str(uuid.uuid4())[:8],
                "type": data["type"],
                "value": float(data["val"]),
                "category": data.get("cat", "Geral"),
                "description": "",
                "date": now.strftime("%d/%m/%Y %H:%M")
            })
            save_db(db)
            await wait.edit_text(f"✅ Registrado: R$ {float(data['val']):.2f}")
            return

        if data.get("type") == "conversa":
            await wait.edit_text(data.get("msg", "Ok."))
            return

        await wait.edit_text("🤖 Não reconhecido.")

    except Exception as e:
        await wait.edit_text(f"⚠️ Erro IA: {str(e)[:100]}")

# ================= MAIN =================
def main():
    print("🚀 Iniciando Bot V95...")

    app_flask = Flask('')
    @app_flask.route('/')
    def home():
        return "Bot Online"

    threading.Thread(
        target=lambda: app_flask.run(host='0.0.0.0', port=10000),
        daemon=True
    ).start()

    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", smart_entry))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_entry))

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, 'interval', minutes=1, args=[app_bot])
    scheduler.start()

    app_bot.run_polling()

if __name__ == "__main__":
    main()