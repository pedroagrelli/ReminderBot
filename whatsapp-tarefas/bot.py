import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from google import genai
from pydantic import BaseModel, Field, field_validator


TIMEZONE = ZoneInfo("America/Sao_Paulo")
DATABASE_PATH = Path(__file__).with_name("tasks.db")


class InterpretedMessage(BaseModel):
    intent: Literal[
        "add_task",
        "create_reminder",
        "list_tasks",
        "complete_task",
        "set_daily_summary",
        "unknown",
    ] = Field(description="A ação que a pessoa deseja realizar.")
    task: str | None = Field(
        default=None,
        description="Descrição da tarefa ou referência usada para concluí-la.",
    )
    scheduled_at: datetime | None = Field(
        default=None,
        description="Data e hora do lembrete com fuso horário, ou null.",
    )
    clarification_question: str | None = Field(
        default=None,
        description="Pergunta curta se faltar informação necessária, ou null.",
    )
    daily_summary_time: str | None = Field(
        default=None,
        description="Horário diário no formato HH:MM, ou null.",
    )
    daily_summary_enabled: bool | None = Field(
        default=None,
        description="True para ativar ou atualizar; False para desativar.",
    )

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_include_timezone(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("O horário do lembrete precisa incluir fuso horário.")
        return value

    @field_validator("daily_summary_time")
    @classmethod
    def daily_summary_time_must_be_valid(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.strptime(value, "%H:%M")
        return value


class TaskStore:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    scheduled_at TEXT,
                    completed INTEGER NOT NULL DEFAULT 0,
                    reminder_sent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)")
            }
            if "reminder_sent" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN reminder_sent "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    daily_summary_time TEXT,
                    daily_summary_sent_date TEXT
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO bot_settings (id) VALUES (1)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def add(self, description: str, scheduled_at: datetime | None = None) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (description, scheduled_at, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    description,
                    scheduled_at.isoformat() if scheduled_at else None,
                    datetime.now(TIMEZONE).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def pending(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT id, description, scheduled_at FROM tasks "
                    "WHERE completed = 0 ORDER BY id"
                )
            )

    def due_reminders(self, now: datetime) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, description, scheduled_at
                    FROM tasks
                    WHERE completed = 0
                      AND reminder_sent = 0
                      AND scheduled_at IS NOT NULL
                      AND julianday(scheduled_at) <= julianday(?)
                    ORDER BY scheduled_at, id
                    """,
                    (now.isoformat(),),
                )
            )

    def mark_reminder_sent(self, task_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET reminder_sent = 1 WHERE id = ?",
                (task_id,),
            )

    def set_daily_summary(self, time: str | None) -> None:
        if time is not None:
            datetime.strptime(time, "%H:%M")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE bot_settings
                SET daily_summary_time = ?, daily_summary_sent_date = NULL
                WHERE id = 1
                """,
                (time,),
            )

    def daily_summary_due(self, now: datetime) -> tuple[str, str] | None:
        with self._connect() as connection:
            settings = connection.execute(
                """
                SELECT daily_summary_time, daily_summary_sent_date
                FROM bot_settings WHERE id = 1
                """
            ).fetchone()
            if settings is None or settings["daily_summary_time"] is None:
                return None

            today = now.date().isoformat()
            if (
                now.strftime("%H:%M") < settings["daily_summary_time"]
                or settings["daily_summary_sent_date"] == today
            ):
                return None
            return settings["daily_summary_time"], today

    def mark_daily_summary_sent(self, sent_date: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE bot_settings
                SET daily_summary_sent_date = ?
                WHERE id = 1
                """,
                (sent_date,),
            )

    def complete(self, task_reference: str) -> int | None:
        with self._connect() as connection:
            tasks = connection.execute(
                "SELECT id, description FROM tasks WHERE completed = 0 ORDER BY id"
            ).fetchall()

            if task_reference.isdigit():
                matches = [task for task in tasks if task["id"] == int(task_reference)]
            else:
                reference = task_reference.casefold()
                matches = [
                    task
                    for task in tasks
                    if reference in task["description"].casefold()
                ]

            if len(matches) != 1:
                return None

            task_id = matches[0]["id"]
            connection.execute(
                "UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,)
            )
            return int(task_id)


def format_pending_tasks(store: TaskStore) -> str:
    tasks = store.pending()
    if not tasks:
        return "Você não tem tarefas pendentes."

    lines = ["Suas tarefas pendentes:"]
    for task in tasks:
        line = f"{task['id']}. {task['description']}"
        if task["scheduled_at"]:
            scheduled_at = datetime.fromisoformat(task["scheduled_at"])
            line += f" — lembrete em {scheduled_at:%d/%m/%Y às %H:%M}"
        lines.append(line)
    return "\n".join(lines)


def interpret_message(
    message: str,
    pending_reminder_task: str | None = None,
    api_key: str | None = None,
) -> InterpretedMessage:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não está definida neste terminal.")

    now = datetime.now(TIMEZONE)
    context = ""
    if pending_reminder_task:
        context = (
            "Você perguntou o horário de um lembrete para esta tarefa: "
            f"{pending_reminder_task!r}. Interprete a mensagem atual como "
            "resposta a essa pergunta; mantenha intent=create_reminder e "
            "use essa tarefa. Se a mensagem não informar um horário válido, "
            "peça esclarecimento novamente.\n"
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=(
            f"Agora é {now.isoformat()} no fuso America/Sao_Paulo.\n"
            "Interprete a mensagem em português para um bot pessoal de tarefas.\n"
            f"{context}"
            "Escolha uma intenção: add_task, create_reminder, list_tasks, "
            "complete_task, set_daily_summary ou unknown. Em complete_task, "
            "retorne em task o número/ID ou uma descrição curta que identifique "
            "a tarefa. Para resumo diário, use set_daily_summary e retorne "
            "daily_summary_enabled=true e daily_summary_time em HH:MM no fuso "
            "local; para desativar, use daily_summary_enabled=false.\n"
            "Use create_reminder quando a pessoa pedir para ser lembrada; "
            "se faltar a tarefa ou o horário, deixe o campo ausente e faça "
            "uma pergunta de esclarecimento.\n"
            "Resolva datas relativas usando a data e hora informadas acima. "
            "scheduled_at deve ser uma data ISO 8601 com fuso "
            "America/Sao_Paulo. Não invente datas ou horários.\n"
            f"Mensagem: {message}"
        ),
        config={
            "response_mime_type": "application/json",
            "response_schema": InterpretedMessage,
        },
    )

    if response.parsed is None:
        raise RuntimeError("O Gemini não retornou uma interpretação estruturada.")

    return InterpretedMessage.model_validate(response.parsed)


def process_message(
    message: str,
    store: TaskStore,
    pending_reminder_task: str | None = None,
) -> tuple[str, str | None]:
    interpreted = interpret_message(message, pending_reminder_task)

    if interpreted.intent == "list_tasks":
        return format_pending_tasks(store), None

    if interpreted.intent == "add_task":
        if not interpreted.task:
            return "Qual tarefa você quer adicionar?", None
        task_id = store.add(interpreted.task)
        return f"Tarefa adicionada com o número {task_id}.", None

    if interpreted.intent == "create_reminder":
        if not interpreted.task:
            return (
                interpreted.clarification_question
                or "Qual tarefa você quer que eu lembre?",
                None,
            )
        if not interpreted.scheduled_at:
            return (
                interpreted.clarification_question
                or "Para quando devo agendar o lembrete?",
                interpreted.task,
            )
        if interpreted.scheduled_at <= datetime.now(TIMEZONE):
            return (
                "Esse horário já passou. Para quando devo agendar o lembrete?",
                interpreted.task,
            )

        task_id = store.add(interpreted.task, interpreted.scheduled_at)
        return (
            f"Registrei a tarefa {task_id} para "
            f"{interpreted.scheduled_at:%d/%m/%Y às %H:%M}. "
            "Vou te avisar aqui no Telegram nesse horário.",
            None,
        )

    if interpreted.intent == "complete_task":
        if not interpreted.task:
            return "Qual tarefa devo marcar como concluída?", None
        task_id = store.complete(interpreted.task.strip())
        if task_id is None:
            return (
                "Não encontrei uma única tarefa correspondente. "
                "Use o número que aparece na lista de tarefas.",
                None,
            )
        return f"Tarefa {task_id} marcada como concluída.", None

    if interpreted.intent == "set_daily_summary":
        if interpreted.daily_summary_enabled is False:
            store.set_daily_summary(None)
            return "Resumo diário desativado.", None
        if not interpreted.daily_summary_time:
            return (
                interpreted.clarification_question
                or "Que horas você quer receber o resumo diário? "
                "Envie novamente o pedido junto com o horário.",
                None,
            )
        store.set_daily_summary(interpreted.daily_summary_time)
        return (
            "Resumo diário ativado para todos os dias às "
            f"{interpreted.daily_summary_time} (horário de São Paulo).",
            None,
        )

    return (
        "Não entendi o pedido. Você pode pedir para adicionar, "
        "listar ou concluir uma tarefa.",
        None,
    )
