# Bot pessoal de tarefas no Telegram

O bot usa a API do Telegram por polling, o Gemini para interpretar mensagens e
SQLite para guardar tarefas localmente. Não precisa de URL pública nem de AWS
para executar esta versão.

## Preparar

1. Crie um bot com `@BotFather` no Telegram usando `/newbot` e guarde o token
   retornado em segredo.
2. Ative o ambiente e instale as dependências:

   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. Carregue os segredos no terminal, sem incluí-los no código:

   ```bash
   read -s -p "Token do BotFather: " TELEGRAM_BOT_TOKEN
   export TELEGRAM_BOT_TOKEN
   echo

   read -s -p "Chave do Gemini: " GEMINI_API_KEY
   export GEMINI_API_KEY
   echo
   ```

4. Inicie o bot:

   ```bash
   python telegram_app.py
   ```

5. Abra seu bot no Telegram e envie `/id`. Anote o número retornado, pare o
   processo com `Ctrl+C` e configure seu ID como permitido:

   ```bash
   export TELEGRAM_ALLOWED_USER_ID=SEU_ID_NUMERICO
   python telegram_app.py
   ```

6. Envie `/start` e converse com o bot. O ID permitido evita que outras pessoas
   usem a lista de tarefas.

## Exemplos

- `Adicione comprar pão`
- `O que tenho para fazer?`
- `Concluí a tarefa 1`
- `Me lembre de beber água amanhã às 9h`
- `Me envie um resumo das tarefas todos os dias às 8h`
- `Desative o resumo diário`

Na execução local, as tarefas e os horários ficam em `tasks.db`. O bot verifica
lembretes vencidos a cada 15 segundos e precisa permanecer rodando para enviar
no horário.

## Publicar na AWS

O modo AWS usa API Gateway e Lambda para o webhook do Telegram, DynamoDB para
tarefas e EventBridge Scheduler para lembretes e resumo diário. Configure o
perfil AWS `default` com permissões para criar CloudFormation, IAM, Lambda,
API Gateway, DynamoDB, EventBridge Scheduler, Secrets Manager e recursos de
bootstrap do CDK. O projeto sintetiza por padrão na região `us-east-1`.

1. Pare o bot local com `Ctrl+C` e, na pasta do projeto, prepare o pacote da
   Lambda e confira a stack localmente:

   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements-cdk.txt
   python build_lambda.py
   npm exec --yes --package=node@22 --package=aws-cdk@2 -- cdk synth
   ```

2. Confira a conta com `aws sts get-caller-identity`. Substitua `ACCOUNT_ID`
   pelo número retornado e prepare a conta para o CDK:

   ```bash
   npm exec --yes --package=node@22 --package=aws-cdk@2 -- \
     cdk bootstrap aws://ACCOUNT_ID/us-east-1
   ```

3. Revise os recursos exibidos e publique a aplicação:

   ```bash
   npm exec --yes --package=node@22 --package=aws-cdk@2 -- \
     cdk deploy --require-approval broadening
   ```

4. Execute `python configure_aws.py`. O script pergunta o token do BotFather,
   a chave Gemini e seu ID numérico do Telegram sem mostrar os segredos na
   entrada, guarda-os no Secrets Manager e registra o webhook na API do
   Telegram. Não execute o bot local por polling ao mesmo tempo.
5. Envie `/start` ao bot e teste. O banco local `tasks.db` não é migrado
   automaticamente para o DynamoDB.

Os serviços AWS podem gerar custos conforme uso e região. Secrets Manager tem
custo mensal por segredo; API Gateway, Lambda, DynamoDB, EventBridge Scheduler,
S3 usado pelo CDK e CloudWatch podem cobrar por uso ou armazenamento. Consulte
os preços atuais da AWS antes de publicar. A tabela e o segredo têm política de
retenção, então remover a stack não os apaga automaticamente.
# ReminderBot
