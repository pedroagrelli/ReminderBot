# 🤖 Bot Pessoal de Tarefas no Telegram

Um assistente pessoal inteligente no Telegram que utiliza a **API do Gemini** para interpretar linguagem natural e gerenciar seus lembretes e tarefas. 

Este projeto foi desenhado com duas abordagens de execução:
1. **Modo Local (Polling):** Rápido para testar na sua máquina, usando SQLite e a API do Telegram por polling (sem necessidade de servidor em nuvem ou URL pública).
2. **Modo Nuvem (AWS Serverless):** Focado em produção e estabilidade, usando arquitetura AWS (API Gateway, Lambda, DynamoDB e EventBridge Scheduler).

---

## 📸 Demonstração

<p align="center">
  <img width="300" alt="Chat no telegram" src="https://github.com/user-attachments/assets/4c0a4987-9fa0-49a4-a6cf-e9bf66636861" />
  <img width="300" alt="Notificação na tela de bloqueio" src="https://github.com/user-attachments/assets/8f4b91aa-746b-40c8-aadc-c89cf01b0486" />
</p>

*Exemplo do bot em funcionamento agendando tarefas em linguagem natural e enviando notificações na tela de bloqueio.*

---

## 🔒 Segurança em Primeiro Lugar
O bot implementa uma trava de segurança via `TELEGRAM_ALLOWED_USER_ID`. Apenas o seu próprio usuário do Telegram terá permissão para visualizar, criar ou concluir tarefas. Isso garante que sua lista seja totalmente privada, mesmo que outra pessoa encontre o seu bot.

---

## 💬 Exemplos de Uso
Uma vez rodando, o bot compreende a sua intenção em linguagem natural. Você pode enviar:
- *"Adicione comprar pão"*
- *"O que tenho para fazer?"*
- *"Concluí a tarefa 1"*
- *"Me lembre de beber água amanhã às 9h"*
- *"Me envie um resumo das tarefas todos os dias às 8h"*
- *"Desative o resumo diário"*

---

## 💻 1. Rodando Localmente (Modo Polling)

Neste modo, as tarefas ficam armazenadas localmente em um arquivo `tasks.db` (SQLite). O script faz verificações a cada 15 segundos em busca de lembretes vencidos. **É necessário manter o terminal aberto para que o bot funcione e envie os lembretes.**

### Preparação Inicial

1. **Crie o Bot no Telegram:**
   Abra o Telegram, converse com o [@BotFather](https://t.me/botfather), use o comando `/newbot` e guarde o **Token** retornado em segredo.

2. **Ative o ambiente virtual e instale as dependências:**
   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. **Carregue os segredos no terminal:**
   *Essa abordagem evita colocar as chaves direto no código.*
   ```bash
   read -s -p "Token do BotFather: " TELEGRAM_BOT_TOKEN
   export TELEGRAM_BOT_TOKEN
   echo

   read -s -p "Chave do Gemini: " GEMINI_API_KEY
   export GEMINI_API_KEY
   echo
   ```

4. **Descubra o seu ID do Telegram e inicie o bot:**
   Primeiro, inicie o bot provisoriamente:
   ```bash
   python telegram_app.py
   ```
   Abra o seu bot no Telegram e envie o comando `/id`. O bot retornará um número. Anote esse número.
   Pare o processo no terminal apertando `Ctrl+C`.

5. **Configure o seu ID de segurança e inicie definitivamente:**
   ```bash
   export TELEGRAM_ALLOWED_USER_ID=SEU_ID_NUMERICO_AQUI
   python telegram_app.py
   ```
   Agora basta mandar `/start` no Telegram e conversar com o bot!

---

## ☁️ 2. Publicando na AWS (Modo Serverless)

Neste modo, o bot ganha escalabilidade extrema e roda 24/7 sem que seu computador precise estar ligado. Ele utiliza **API Gateway** e **Lambda** (para receber os webhooks do Telegram), **DynamoDB** (como banco de dados de tarefas), **EventBridge Scheduler** (para os lembretes exatos e rotinas de resumo diário) e **Secrets Manager** (para armazenar as chaves de API com segurança).

> [!NOTE]
> O banco local `tasks.db` criado no ambiente de teste não é migrado automaticamente para o DynamoDB.

### Preparação da Nuvem

Configure o seu profile padrão do AWS CLI (`aws configure`) com permissões para criar todos os recursos necessários (CloudFormation, IAM, Lambda, API Gateway, DynamoDB, EventBridge Scheduler e Secrets Manager). O projeto sintetiza por padrão na região `us-east-1`.

1. **Pare o bot local** (com `Ctrl+C`) e prepare o ambiente da nuvem:
   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements-cdk.txt
   ```

2. **Gere o pacote da Lambda e confira a Stack localmente:**
   ```bash
   python build_lambda.py
   npm exec --yes --package=node@22 --package=aws-cdk@2 -- cdk synth
   ```

3. **Faça o Bootstrap da AWS:**
   Descubra o ID da sua conta rodando `aws sts get-caller-identity`. Substitua a palavra `ACCOUNT_ID` pelo seu número retornado no comando abaixo:
   ```bash
   npm exec --yes --package=node@22 --package=aws-cdk@2 -- \
     cdk bootstrap aws://ACCOUNT_ID/us-east-1
   ```

4. **Realize o Deploy (Publicação):**
   ```bash
   npm exec --yes --package=node@22 --package=aws-cdk@2 -- \
     cdk deploy --require-approval broadening
   ```

### Configuração Pós-Deploy

O último passo é configurar a infraestrutura de nuvem com as suas chaves e configurar a URL (Webhook) na API do Telegram. 

Execute o script mágico de configuração:
```bash
python configure_aws.py
```
O script fará perguntas sobre o *Token do BotFather*, a *Chave do Gemini* e seu *ID Numérico* (de forma oculta). Ele cuidará de salvar esses dados no AWS Secrets Manager e registrar a URL do API Gateway como o webhook oficial do seu bot no Telegram.

> [!IMPORTANT]
> Após configurar o webhook, **não execute o bot localmente (polling) ao mesmo tempo**. O Telegram não permite que um webhook e uma conexão de polling concorram pelo mesmo token.

Envie `/start` ao bot no Telegram e aproveite sua infraestrutura serverless na nuvem!

---

## 💰 Avisos sobre Custos e Retenção na AWS

Os serviços AWS provisionados via CDK podem gerar custos conforme o seu nível de uso e a região selecionada. O **Secrets Manager**, por exemplo, possui um custo mensal fixo por segredo armazenado. Serviços como API Gateway, Lambda, DynamoDB, EventBridge Scheduler, CloudWatch e o S3 (usado pelo CDK bootstrap) possuem cobranças baseadas em volume de uso ou armazenamento, embora contem com *Free Tiers* generosos. 

Consulte sempre a [página de preços atual da AWS](https://aws.amazon.com/pricing/) antes de publicar recursos na sua conta pessoal.

**Nota sobre a remoção da Stack:** Por segurança de dados, a tabela do DynamoDB e o segredo no Secrets Manager possuem políticas de retenção configuradas. Caso você rode o comando para destruir a stack (ex: `cdk destroy`), esses dois recursos **não** serão apagados automaticamente e precisarão ser deletados manualmente pelo console da AWS para evitar cobranças remanescentes.
