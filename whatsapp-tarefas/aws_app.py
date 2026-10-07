import base64
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from google.genai.errors import APIError
from pydantic import ValidationError

from bot import TIMEZONE, format_pending_tasks, interpret_message


logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TASKS_TABLE_NAME"])
scheduler = boto3.client("scheduler")
secrets_client = boto3.client("secretsmanager")
_secret_cache: dict[str, str] | None = None


class DynamoTaskStore:
    def __init__(self, chat_id: str) -> None:
        self.pk = f"USER#{chat_id}"

    def get_settings(self) -> dict:
        response = table.get_item(
            Key={"pk": self.pk, "sk": "SETTINGS"},
            ConsistentRead=True,
        )
        return response.get("Item", {})

    def set_setting(self, name: str, value: str | None) -> None:
        if value is None:
            table.update_item(
                Key={"pk": self.pk, "sk": "SETTINGS"},
                UpdateExpression="REMOVE #name",
                ExpressionAttributeNames={"#name": name},
            )
            return
        table.update_item(
            Key={"pk": self.pk, "sk": "SETTINGS"},
            UpdateExpression="SET #name = :value",
            ExpressionAttributeNames={"#name": name},
            ExpressionAttributeValues={":value": value},
        )

    def add(self, description: str, scheduled_at: datetime | None = None) -> int:
        response = table.update_item(
            Key={"pk": self.pk, "sk": "COUNTER"},
            UpdateExpression="ADD #counter :one",
            ExpressionAttributeNames={"#counter": "value"},
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        task_id = int(response["Attributes"]["value"])
        item = {
            "pk": self.pk,
            "sk": f"TASK#{task_id:010d}",
            "task_id": task_id,
            "description": description,
            "completed": False,
            "reminder_sent": False,
            "created_at": datetime.now(TIMEZONE).isoformat(),
        }
        if scheduled_at is not None:
            item["scheduled_at"] = scheduled_at.isoformat()
        table.put_item(Item=item)
        return task_id

    def pending(self) -> list[dict]:
        response = table.query(
            KeyConditionExpression=Key("pk").eq(self.pk)
            & Key("sk").begins_with("TASK#"),
            ConsistentRead=True,
        )
        tasks = response["Items"]
        while "LastEvaluatedKey" in response:
            response = table.query(
                KeyConditionExpression=Key("pk").eq(self.pk)
                & Key("sk").begins_with("TASK#"),
                ConsistentRead=True,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            tasks.extend(response["Items"])
        pending = [task for task in tasks if not task.get("completed", False)]
        for task in pending:
            task["id"] = task["task_id"]
        return pending

    def get_task(self, task_id: int) -> dict | None:
        response = table.get_item(
            Key={"pk": self.pk, "sk": f"TASK#{task_id:010d}"},
            ConsistentRead=True,
        )
        return response.get("Item")

    def complete(self, reference: str) -> int | None:
        tasks = self.pending()
        if reference.isdigit():
            matches = [task for task in tasks if task["task_id"] == int(reference)]
        else:
            needle = reference.casefold()
            matches = [
                task
                for task in tasks
                if needle in task["description"].casefold()
            ]
        if len(matches) != 1:
            return None
        task = matches[0]
        table.update_item(
            Key={"pk": self.pk, "sk": task["sk"]},
            UpdateExpression="SET completed = :true",
            ExpressionAttributeValues={":true": True},
        )
        return int(task["task_id"])

    def mark_reminder_sent(self, task_id: int) -> None:
        table.update_item(
            Key={"pk": self.pk, "sk": f"TASK#{task_id:010d}"},
            UpdateExpression="SET reminder_sent = :true",
            ExpressionAttributeValues={":true": True},
        )


def _secrets() -> dict[str, str]:
    global _secret_cache
    if _secret_cache is None:
        response = secrets_client.get_secret_value(
            SecretId=os.environ["BOT_SECRET_ARN"]
        )
        _secret_cache = json.loads(response["SecretString"])
    return _secret_cache


def _send_telegram_message(chat_id: str, text: str, token: str) -> None:
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise RuntimeError(
            f"Telegram API returned HTTP {error.code}."
        ) from None
    except URLError:
        raise RuntimeError("Could not connect to the Telegram API.") from None
    if not result.get("ok"):
        raise RuntimeError("Telegram recusou o envio da mensagem.")


def _schedule(
    name: str,
    expression: str,
    input_payload: dict,
    timezone_name: str,
    one_time: bool,
) -> None:
    args = {
        "Name": name,
        "GroupName": os.environ["SCHEDULE_GROUP_NAME"],
        "ScheduleExpression": expression,
        "ScheduleExpressionTimezone": timezone_name,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {
            "Arn": os.environ["WORKER_FUNCTION_ARN"],
            "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
            "Input": json.dumps(input_payload),
            "RetryPolicy": {
                "MaximumEventAgeInSeconds": 3600,
                "MaximumRetryAttempts": 3,
            },
        },
        "State": "ENABLED",
    }
    if one_time:
        args["ActionAfterCompletion"] = "DELETE"
    try:
        scheduler.create_schedule(**args)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConflictException":
            raise
        scheduler.update_schedule(**args)


def _delete_schedule(name: str) -> None:
    try:
        scheduler.delete_schedule(
            Name=name,
            GroupName=os.environ["SCHEDULE_GROUP_NAME"],
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise


def _set_daily_schedule(chat_id: str, time: str | None) -> None:
    name = f"daily-{chat_id}"
    if time is None:
        _delete_schedule(name)
        return
    hour, minute = (int(part) for part in time.split(":"))
    _schedule(
        name=name,
        expression=f"cron({minute} {hour} * * ? *)",
        input_payload={"job": "daily_summary", "chat_id": chat_id},
        timezone_name="America/Sao_Paulo",
        one_time=False,
    )


def _handle_user_message(update: dict, config: dict) -> None:
    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return
    sender = message.get("from", {})
    chat = message.get("chat", {})
    allowed_user_id = config.get("TELEGRAM_ALLOWED_USER_ID")
    if (
        not allowed_user_id
        or str(sender.get("id")) != allowed_user_id
        or str(chat.get("id")) != allowed_user_id
    ):
        return

    chat_id = str(chat["id"])
    text = message["text"].strip()
    if text.startswith("/start"):
        _send_telegram_message(
            chat_id,
            "Bot de tarefas pronto! Escreva naturalmente para adicionar "
            "tarefas, consultar a lista e agendar lembretes.",
            config["TELEGRAM_BOT_TOKEN"],
        )
        return

    store = DynamoTaskStore(chat_id)
    settings = store.get_settings()
    interpreted = interpret_message(
        text,
        settings.get("pending_reminder_task"),
        api_key=config["GEMINI_API_KEY"],
    )
    if interpreted.intent == "create_reminder":
        if interpreted.task and not interpreted.scheduled_at:
            store.set_setting("pending_reminder_task", interpreted.task)
        else:
            store.set_setting("pending_reminder_task", None)

    if interpreted.intent == "list_tasks":
        reply = format_pending_tasks(store)
    elif interpreted.intent == "add_task":
        if not interpreted.task:
            reply = "Qual tarefa você quer adicionar?"
        else:
            task_id = store.add(interpreted.task)
            reply = f"Tarefa adicionada com o número {task_id}."
    elif interpreted.intent == "create_reminder":
        if not interpreted.task:
            reply = (
                interpreted.clarification_question
                or "Qual tarefa você quer que eu lembre?"
            )
        elif not interpreted.scheduled_at:
            reply = (
                interpreted.clarification_question
                or "Para quando devo agendar o lembrete?"
            )
        elif interpreted.scheduled_at <= datetime.now(TIMEZONE):
            store.set_setting("pending_reminder_task", interpreted.task)
            reply = "Esse horário já passou. Para quando devo agendar?"
        else:
            task_id = store.add(interpreted.task, interpreted.scheduled_at)
            try:
                utc_time = interpreted.scheduled_at.astimezone(timezone.utc)
                expression_time = utc_time.strftime("%Y-%m-%dT%H:%M:%S")
                _schedule(
                    name=f"task-{chat_id}-{task_id}",
                    expression=f"at({expression_time})",
                    input_payload={
                        "job": "reminder",
                        "chat_id": chat_id,
                        "task_id": task_id,
                    },
                    timezone_name="UTC",
                    one_time=True,
                )
            except (ClientError, ValueError, KeyError):
                store.complete(str(task_id))
                raise
            reply = (
                f"Agendei a tarefa {task_id} para "
                f"{interpreted.scheduled_at:%d/%m/%Y às %H:%M}."
            )
    elif interpreted.intent == "complete_task":
        if not interpreted.task:
            reply = "Qual tarefa devo marcar como concluída?"
        else:
            task_id = store.complete(interpreted.task.strip())
            if task_id is None:
                reply = (
                    "Não encontrei uma única tarefa correspondente. "
                    "Use o número que aparece na lista."
                )
            else:
                _delete_schedule(f"task-{chat_id}-{task_id}")
                reply = f"Tarefa {task_id} marcada como concluída."
    elif interpreted.intent == "set_daily_summary":
        if interpreted.daily_summary_enabled is False:
            store.set_setting("daily_summary_time", None)
            _set_daily_schedule(chat_id, None)
            reply = "Resumo diário desativado."
        elif not interpreted.daily_summary_time:
            reply = (
                interpreted.clarification_question
                or "Que horas você quer receber o resumo diário?"
            )
        else:
            store.set_setting(
                "daily_summary_time", interpreted.daily_summary_time
            )
            _set_daily_schedule(chat_id, interpreted.daily_summary_time)
            reply = (
                "Resumo diário ativado para todos os dias às "
                f"{interpreted.daily_summary_time} (horário de São Paulo)."
            )
    else:
        reply = (
            "Não entendi. Você pode pedir para adicionar, listar ou concluir "
            "uma tarefa, ou agendar um lembrete."
        )

    _send_telegram_message(chat_id, reply, config["TELEGRAM_BOT_TOKEN"])


def _handle_scheduled_job(event: dict, config: dict) -> None:
    chat_id = str(event["chat_id"])
    store = DynamoTaskStore(chat_id)
    if event.get("job") == "reminder":
        task_id = int(event["task_id"])
        task = store.get_task(task_id)
        if task is None or task.get("completed") or task.get("reminder_sent"):
            return
        scheduled_at = datetime.fromisoformat(task["scheduled_at"])
        _send_telegram_message(
            chat_id,
            f"Lembrete: {task['description']}\n"
            f"Agendado para {scheduled_at:%d/%m/%Y às %H:%M}.",
            config["TELEGRAM_BOT_TOKEN"],
        )
        store.mark_reminder_sent(task_id)
        return

    if event.get("job") == "daily_summary":
        settings = store.get_settings()
        if not settings.get("daily_summary_time"):
            return
        today = datetime.now(TIMEZONE).date().isoformat()
        if settings.get("daily_summary_sent_date") == today:
            return
        _send_telegram_message(
            chat_id,
            f"Seu resumo diário:\n{format_pending_tasks(store)}",
            config["TELEGRAM_BOT_TOKEN"],
        )
        store.set_setting("daily_summary_sent_date", today)


def _claim_telegram_update(update_id: int) -> bool:
    try:
        table.put_item(
            Item={
                "pk": "SYSTEM#TELEGRAM",
                "sk": f"UPDATE#{update_id}",
                "expires_at": int(time.time()) + 604800,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _release_telegram_update(update_id: int) -> None:
    table.delete_item(
        Key={
            "pk": "SYSTEM#TELEGRAM",
            "sk": f"UPDATE#{update_id}",
        }
    )


def handler(event: dict, context: object) -> dict:
    try:
        if event.get("job"):
            _handle_scheduled_job(event, _secrets())
            return {"statusCode": 200, "body": "ok"}

        headers = {key.lower(): value for key, value in event.get("headers", {}).items()}
        config = _secrets()
        supplied_secret = headers.get("x-telegram-bot-api-secret-token", "")
        expected_secret = config.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not expected_secret or not hmac.compare_digest(
            supplied_secret, expected_secret
        ):
            return {"statusCode": 403, "body": "forbidden"}

        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        update = json.loads(body)
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return {"statusCode": 400, "body": "invalid update"}
        if not _claim_telegram_update(update_id):
            return {"statusCode": 200, "body": "duplicate"}
        try:
            _handle_user_message(update, config)
        except (
            APIError,
            ValidationError,
            ClientError,
            HTTPError,
            URLError,
            RuntimeError,
            ValueError,
            KeyError,
        ):
            _release_telegram_update(update_id)
            raise
        return {"statusCode": 200, "body": "ok"}
    except (
        APIError,
        ValidationError,
        ClientError,
        HTTPError,
        URLError,
        RuntimeError,
        ValueError,
        KeyError,
    ):
        logger.exception("Falha ao processar evento do bot")
        if event.get("job"):
            raise
        return {"statusCode": 500, "body": "processing error"}
