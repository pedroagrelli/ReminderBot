import getpass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3


STACK_NAME = "TaskReminderBotStack"


def required_secret_value(environment_name: str, prompt: str) -> str:
    value = os.environ.get(environment_name)
    if not value:
        value = getpass.getpass(prompt)
    if not value.strip():
        raise ValueError(f"{environment_name} não pode ficar vazio.")
    return value.strip()


def main() -> None:
    cloudformation = boto3.client("cloudformation")
    secrets_manager = boto3.client("secretsmanager")
    stack = cloudformation.describe_stacks(StackName=STACK_NAME)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    secret_response = secrets_manager.get_secret_value(
        SecretId=outputs["BotSecretName"]
    )
    secret = json.loads(secret_response["SecretString"])

    telegram_token = required_secret_value(
        "TELEGRAM_BOT_TOKEN", "Token do BotFather: "
    )
    gemini_key = required_secret_value(
        "GEMINI_API_KEY", "Chave da API Gemini: "
    )
    allowed_user_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    if not allowed_user_id:
        allowed_user_id = input("Seu ID numérico do Telegram: ").strip()
    if not allowed_user_id.isdigit():
        raise ValueError("O ID do Telegram precisa ser numérico.")

    secret.update(
        {
            "TELEGRAM_BOT_TOKEN": telegram_token,
            "GEMINI_API_KEY": gemini_key,
            "TELEGRAM_ALLOWED_USER_ID": allowed_user_id,
        }
    )
    secrets_manager.put_secret_value(
        SecretId=outputs["BotSecretName"],
        SecretString=json.dumps(secret),
    )

    request = Request(
        f"https://api.telegram.org/bot{telegram_token}/setWebhook",
        data=json.dumps(
            {
                "url": outputs["TelegramWebhookUrl"],
                "secret_token": secret["TELEGRAM_WEBHOOK_SECRET"],
                "allowed_updates": ["message"],
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise SystemExit(
            f"Telegram recusou a configuração do webhook (HTTP {error.code})."
        ) from None
    except URLError:
        raise SystemExit(
            "Não foi possível conectar à API do Telegram para configurar o webhook."
        ) from None

    if not result.get("ok"):
        raise SystemExit("Telegram não aceitou a configuração do webhook.")

    print("Segredos guardados e webhook do Telegram configurado.")
    print("Agora envie /start ao bot e teste uma tarefa.")


if __name__ == "__main__":
    main()
