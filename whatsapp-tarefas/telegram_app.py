import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from google.genai.errors import APIError
from pydantic import ValidationError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import TIMEZONE, TaskStore, format_pending_tasks, process_message


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
STORE = TaskStore()


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    await message.reply_text(
        f"Seu ID do Telegram é {user.id}. "
        "Configure TELEGRAM_ALLOWED_USER_ID com esse número no terminal, "
        "reinicie o bot e envie /start."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    allowed_user_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    if not allowed_user_id:
        await message.reply_text(
            "Para proteger suas tarefas, primeiro envie /id e configure "
            "TELEGRAM_ALLOWED_USER_ID no terminal."
        )
        return
    if str(user.id) != allowed_user_id:
        await message.reply_text("Este bot está configurado para uso privado.")
        return

    await message.reply_text(
        "Bot de tarefas pronto! Pode escrever naturalmente. "
        "Exemplos: 'adicionar comprar pão', 'o que tenho para fazer?' "
        "ou 'me lembre de beber água amanhã às 9h'."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    allowed_user_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    if not allowed_user_id or str(user.id) != allowed_user_id:
        await message.reply_text(
            "Bot privado. Configure seu acesso com /id e "
            "TELEGRAM_ALLOWED_USER_ID no terminal."
        )
        return

    pending_reminder_task = context.user_data.get("pending_reminder_task")
    try:
        reply, next_pending_reminder_task = await asyncio.to_thread(
            process_message,
            message.text,
            STORE,
            pending_reminder_task,
        )
    except (APIError, ValidationError, RuntimeError, sqlite3.Error):
        logger.exception("Falha ao processar mensagem do Telegram")
        await message.reply_text(
            "Não consegui processar essa mensagem agora. "
            "Confira os logs no terminal e tente novamente."
        )
        return

    if next_pending_reminder_task:
        context.user_data["pending_reminder_task"] = next_pending_reminder_task
    else:
        context.user_data.pop("pending_reminder_task", None)

    await message.reply_text(reply)


async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_user_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    if not allowed_user_id:
        return

    reminders = await asyncio.to_thread(
        STORE.due_reminders,
        datetime.now(TIMEZONE),
    )
    for reminder in reminders:
        scheduled_at = datetime.fromisoformat(reminder["scheduled_at"])
        try:
            await context.bot.send_message(
                chat_id=int(allowed_user_id),
                text=(
                    f"Lembrete: {reminder['description']}\n"
                    f"Agendado para {scheduled_at:%d/%m/%Y às %H:%M}."
                ),
            )
        except TelegramError:
            logger.exception(
                "Não foi possível enviar o lembrete da tarefa %s",
                reminder["id"],
            )
            continue

        await asyncio.to_thread(STORE.mark_reminder_sent, reminder["id"])


async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_user_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    if not allowed_user_id:
        return

    due_summary = await asyncio.to_thread(
        STORE.daily_summary_due,
        datetime.now(TIMEZONE),
    )
    if due_summary is None:
        return

    _, sent_date = due_summary
    summary = await asyncio.to_thread(format_pending_tasks, STORE)
    try:
        await context.bot.send_message(
            chat_id=int(allowed_user_id),
            text=f"Seu resumo diário:\n{summary}",
        )
    except TelegramError:
        logger.exception("Não foi possível enviar o resumo diário")
        return

    await asyncio.to_thread(STORE.mark_daily_summary_sent, sent_date)


async def handle_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if context.error is not None:
        logger.error(
            "Erro não tratado no bot do Telegram",
            exc_info=(
                type(context.error),
                context.error,
                context.error.__traceback__,
            ),
        )


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("id", show_id))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    if application.job_queue is None:
        raise RuntimeError(
            "JobQueue indisponível. Instale python-telegram-bot[job-queue]."
        )
    application.job_queue.run_repeating(
        send_due_reminders,
        interval=15,
        first=1,
        name="due-reminders",
    )
    application.job_queue.run_repeating(
        send_daily_summary,
        interval=30,
        first=1,
        name="daily-summary",
    )
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não está definida no terminal.")
    allowed_user_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    if allowed_user_id and not allowed_user_id.isdigit():
        raise RuntimeError("TELEGRAM_ALLOWED_USER_ID precisa ser numérico.")

    application = build_application(token)
    print("Bot do Telegram iniciado. Pressione Ctrl+C para encerrar.")
    application.run_polling()


if __name__ == "__main__":
    main()
