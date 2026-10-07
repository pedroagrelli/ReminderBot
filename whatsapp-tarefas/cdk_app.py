import os

from aws_cdk import App, Environment

from reminder_stack import ReminderStack


app = App(outdir="cdk.out")
ReminderStack(
    app,
    "TaskReminderBotStack",
    env=Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)
app.synth()
