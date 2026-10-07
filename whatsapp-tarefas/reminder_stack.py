from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_scheduler as scheduler,
    aws_secretsmanager as secretsmanager,
)
from aws_cdk.aws_apigatewayv2 import HttpApi, HttpMethod
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct


class ReminderStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "TasksTable",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.RETAIN,
        )

        scheduler_group_name = "task-reminders"
        worker_function_name = "TaskReminderBotWorker"
        worker_function_arn = (
            f"arn:{self.partition}:lambda:{self.region}:{self.account}:"
            f"function:{worker_function_name}"
        )
        scheduler_group_arn = (
            f"arn:{self.partition}:scheduler:{self.region}:{self.account}:"
            f"schedule/{scheduler_group_name}/*"
        )

        scheduler.CfnScheduleGroup(
            self,
            "ReminderScheduleGroup",
            name=scheduler_group_name,
        )

        worker = lambda_.Function(
            self,
            "TelegramWebhook",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="aws_app.handler",
            code=lambda_.Code.from_asset("lambda_package"),
            function_name=worker_function_name,
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "TASKS_TABLE_NAME": table.table_name,
                "SCHEDULE_GROUP_NAME": scheduler_group_name,
            },
        )

        scheduler_role = iam.Role(
            self,
            "SchedulerInvokeRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[worker_function_arn],
            )
        )
        worker.add_environment("WORKER_FUNCTION_ARN", worker_function_arn)
        worker.add_environment("SCHEDULER_ROLE_ARN", scheduler_role.role_arn)
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "scheduler:CreateSchedule",
                    "scheduler:UpdateSchedule",
                    "scheduler:DeleteSchedule",
                ],
                resources=[scheduler_group_arn],
            )
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[scheduler_role.role_arn],
                conditions={
                    "StringEquals": {
                        "iam:PassedToService": "scheduler.amazonaws.com"
                    }
                },
            )
        )
        table.grant(
            worker,
            "dynamodb:GetItem",
            "dynamodb:Query",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
        )

        secret = secretsmanager.Secret(
            self,
            "BotSecrets",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=(
                    '{"TELEGRAM_BOT_TOKEN":"","GEMINI_API_KEY":"",'
                    '"TELEGRAM_ALLOWED_USER_ID":""}'
                ),
                generate_string_key="TELEGRAM_WEBHOOK_SECRET",
                password_length=48,
                exclude_punctuation=True,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )
        secret.grant_read(worker)
        worker.add_environment("BOT_SECRET_ARN", secret.secret_arn)

        api = HttpApi(self, "TelegramWebhookApi")
        api.add_routes(
            path="/telegram",
            methods=[HttpMethod.POST],
            integration=HttpLambdaIntegration(
                "TelegramWebhookIntegration",
                worker,
            ),
        )

        CfnOutput(
            self,
            "TelegramWebhookUrl",
            value=f"{api.api_endpoint}/telegram",
        )
        CfnOutput(self, "BotSecretName", value=secret.secret_name)
        CfnOutput(self, "TasksTableName", value=table.table_name)
