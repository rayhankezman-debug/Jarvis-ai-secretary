"""
Telegram command and message handlers.

Each handler is a simple async function that receives an Update and Context.
Business logic should NOT live here — handlers are thin wrappers that:
1. Extract data from the Telegram update
2. Call a service/AI layer
3. Send a response back to the user

Handlers:
    /start  — Welcome message + bot introduction
    /help   — List available commands
    /ping   — Quick connectivity check (returns "pong")
    text    — Routes messages to AI for natural language response
"""

import html
import traceback
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /start command.

    This is the first message users see when they open the bot.
    Introduces the bot and its capabilities.
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.first_name}) started the bot")

    welcome_text = (
        f"Halo {html.escape(user.first_name)}! 👋\n\n"
        "Saya <b>AI Secretary</b>, asisten pribadi kamu untuk mengatur:\n\n"
        "📋 <b>Tasks</b> — Buat, update, dan kelola tugas\n"
        "📅 <b>Jadwal</b> — Atur jadwal harian kamu\n"
        "⏰ <b>Reminder</b> — Pengingat otomatis\n"
        "📊 <b>Daily Review</b> — Ringkasan harian\n\n"
        "Kirim pesan apa saja dalam bahasa yang kamu mau, "
        "dan saya akan membantu mengaturnya.\n\n"
        "Ketik /help untuk melihat daftar perintah."
    )

    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /help command.

    Lists all available bot commands with descriptions.
    This will be expanded as new features are added in future phases.
    """
    logger.info(f"User {update.effective_user.id} requested help")

    help_text = (
        "📖 <b>Daftar Perintah</b>\n\n"
        "/start — Mulai bot & lihat intro\n"
        "/help — Tampilkan bantuan ini\n"
        "/ping — Cek koneksi bot\n\n"
        "💬 <b>Cara Pakai</b>\n\n"
        "Cukup kirim pesan biasa, misalnya:\n"
        '<i>"Besok jam 8 kuliah, jam 2 meeting, sore olahraga"</i>\n\n'
        "Saya akan memahami dan membantu mengatur jadwal kamu."
    )

    await update.message.reply_text(help_text, parse_mode="HTML")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /ping command.

    Simple connectivity check. Returns current server time to verify
    the bot is alive and timezone is configured correctly.
    """
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)

    logger.info(f"Ping from user {update.effective_user.id}")

    await update.message.reply_text(
        f"🏓 Pong!\n"
        f"⏰ Server time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🌏 Timezone: {settings.timezone}"
    )


MAX_TELEGRAM_MSG_LEN = 4000


async def _reply_safe(message, text: str, **kwargs) -> None:
    """Send text reply, splitting into multiple messages if over 4000 chars."""
    if len(text) <= MAX_TELEGRAM_MSG_LEN:
        await message.reply_text(text, **kwargs)
    else:
        for i in range(0, len(text), MAX_TELEGRAM_MSG_LEN):
            chunk = text[i : i + MAX_TELEGRAM_MSG_LEN]
            await message.reply_text(chunk, **kwargs)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle regular text messages (non-commands).

    Routes the message through the AI agent for tool-calling support.
    Falls back to simple text generation if the agent is unavailable.
    """
    user = update.effective_user
    text = update.message.text

    logger.info(f"Message from user {user.id}: {text[:50]}...")

    # Try AI agent first (Phase 4+ — with tool calling)
    try:
        from app.ai.agent import get_agent

        agent = get_agent()
        if agent is not None:
            ai_response = await agent.process_message(text, telegram_user_id=user.id)
            await _reply_safe(update.message, ai_response)
            logger.info(f"Agent response sent to user {user.id} ({len(ai_response)} chars)")
            return
    except Exception as e:
        logger.error(f"Agent failed for user {user.id}: {e}")
        # Fall through to simple AI

    # Fallback: simple AI text generation (Phase 3)
    try:
        from app.ai import get_llm_provider

        provider = get_llm_provider()

        if provider is not None:
            # AI is available — generate response
            ai_response = await provider.generate_text(text)
            await _reply_safe(update.message, ai_response)
            logger.info(f"AI response sent to user {user.id} ({len(ai_response)} chars)")
            return

    except Exception as e:
        logger.error(f"AI response failed for user {user.id}: {e}")
        # Fall through to fallback response

    # Fallback: AI not configured or failed
    await update.message.reply_text(
        "📝 Pesan diterima!\n\n"
        f'Kamu mengirim: "<i>{html.escape(text[:200])}</i>"\n\n'
        "⚠️ <i>AI belum aktif. Fitur pemahaman bahasa natural "
        "akan tersedia setelah integrasi Gemini AI.</i>",
        parse_mode="HTML",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Global error handler for the bot.

    Catches all unhandled exceptions from handlers and:
    1. Logs the full traceback for debugging
    2. Sends a user-friendly error message (if possible)

    This prevents the bot from silently failing.
    """
    logger.error(
        f"Exception while handling an update: {context.error}",
        exc_info=context.error,
    )

    # Log the traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    logger.error(f"Traceback:\n{tb_string}")

    # Try to notify the user
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Maaf, terjadi kesalahan internal.\n"
                "Silakan coba lagi nanti."
            )
        except Exception:
            # If we can't even send the error message, just log it
            logger.error("Failed to send error message to user")
