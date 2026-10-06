# 🤖 Daily Summary Bot (AWS Serverless + Gemini AI + Telegram)

Um assistente pessoal inteligente no Telegram que entende linguagem natural para gerenciar e agendar tarefas e lembretes. Construído com uma arquitetura **100% Serverless na AWS**, utilizando o poder do **Google Gemini** para Processamento de Linguagem Natural (NLP) e o **AWS CDK** para Infraestrutura como Código (IaC).

## 🌟 Destaques do Projeto

Este projeto foi desenvolvido com foco em escalabilidade, eficiência de custos e melhores práticas de engenharia de software na nuvem:

* **Compreensão de Linguagem Natural (NLP):** Em vez de comandos rígidos como `/lembrar 2026-10-10 14:00 Comprar pão`, o usuário pode simplesmente enviar *"Me lembre de comprar pão amanhã às duas da tarde"*. O **Google Gemini API** processa o texto, identifica a intenção (criar, listar, concluir) e formata a data/hora exata lidando automaticamente com fusos horários (`America/Sao_Paulo`).
* **Agendamentos de Alta Precisão:** Utiliza o **Amazon EventBridge Scheduler** para criar agendamentos *one-off* (únicos) precisos no nível do minuto. Diferente de arquiteturas de *polling* tradicionais (onde um script roda a cada minuto varrendo o banco de dados), aqui a Lambda de envio é invocada *apenas* no exato momento do lembrete, otimizando os custos na nuvem para próximo de zero.
* **Infraestrutura como Código (IaC):** Toda a infraestrutura da AWS é provisionada via código Python utilizando o **AWS Cloud Development Kit (CDK)**, garantindo que o ambiente seja reprodutível, versionado e de fácil manutenção.
* **Segurança em Primeiro Lugar:** Nenhum token (Telegram, Gemini) fica exposto no código ou em variáveis de ambiente abertas. Todos os segredos são gerenciados e criptografados pelo **AWS Secrets Manager**.

## 🏗️ Arquitetura

A arquitetura foi desenhada para ser orientada a eventos (*Event-Driven*):

1. **Telegram API:** O usuário envia uma mensagem no Telegram. O Telegram dispara um Webhook.
2. **Amazon API Gateway:** Recebe o Webhook do Telegram de forma segura e aciona a primeira função Lambda.
3. **Lambda (Webhook Handler):** 
   - Recebe o payload do Telegram.
   - Envia o texto da mensagem para o **Google Gemini API**.
   - O Gemini retorna um JSON estruturado com a `intenção` e os `dados` (ex: tarefa e horário).
   - A Lambda grava a nova tarefa no **Amazon DynamoDB**.
   - A Lambda cria dinamicamente um *Schedule* no **Amazon EventBridge Scheduler** para o momento exato do lembrete.
4. **Lambda (Reminder Worker):** 
   - No momento exato agendado, o EventBridge Scheduler invoca esta Lambda passando o ID da tarefa.
   - A função busca as informações adicionais, se necessário, marca como enviada no DynamoDB, e dispara a mensagem de volta para o usuário através da API do Telegram.

![AWS Architecture](https://img.shields.io/badge/AWS-Serverless_Architecture-FF9900?style=for-the-badge&logo=amazonaws)

## 🛠️ Tecnologias Utilizadas

* **Linguagem:** Python 3.12+
* **Cloud Provider:** Amazon Web Services (AWS)
* **IaC:** AWS CDK (Cloud Development Kit)
* **Computação:** AWS Lambda
* **Banco de Dados:** Amazon DynamoDB (NoSQL)
* **Agendamento:** Amazon EventBridge Scheduler
* **Segurança:** AWS Secrets Manager, AWS IAM
* **Inteligência Artificial:** Google Gemini (SDK `google-genai`)
* **Interface:** Telegram Bot API

## 🚀 Como Executar o Projeto

### Pré-requisitos
* Node.js instalado (para o AWS CDK).
* AWS CLI configurada com credenciais válidas.
* Um Token de Bot do Telegram (obtido via `@BotFather`).
* Uma Chave de API do Google Gemini.

### Passos para Deploy

1. **Clone o repositório e acesse a pasta:**
   ```bash
   git clone https://github.com/seu-usuario/daily-summary-bot.git
   cd daily-summary-bot
   ```

2. **Crie e ative o ambiente virtual Python:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Instale as dependências da Lambda (Google GenAI) na pasta `src/`:**
   ```bash
   pip install google-genai pydantic requests -t ./src/
   ```

4. **Realize o deploy da infraestrutura usando o CDK:**
   ```bash
   cdk bootstrap # (Apenas na primeira vez na conta/região)
   cdk deploy
   ```

5. **Configure os Segredos na AWS:**
   - Acesse o painel do **AWS Secrets Manager**.
   - Edite o segredo criado pela stack (ex: `whatsapp-bot-secrets` que agora usaremos para o Telegram) e insira seus tokens:
   ```json
   {
     "TELEGRAM_BOT_TOKEN": "seu_token_aqui",
     "GEMINI_API_KEY": "sua_chave_aqui"
   }
   ```

6. **Configure o Webhook do Telegram:**
   - Pegue a URL gerada pelo API Gateway ao final do `cdk deploy`.
   - Faça uma requisição GET ou POST no seu navegador/Postman para vincular o Telegram à sua API:
   ```text
   https://api.telegram.org/bot<SEU_TELEGRAM_BOT_TOKEN>/setWebhook?url=<SUA_URL_DO_API_GATEWAY>
   ```

## 🎯 Próximos Passos (Roadmap)
- [ ] Suporte a áudio: Permitir que o usuário envie mensagens de voz, converter para texto usando Whisper (ou o próprio Gemini) e agendar.
- [ ] Relatório Diário: Uma rotina matinal que resume todas as tarefas agendadas para o dia atual.

---
*Desenvolvido como projeto prático para aprofundamento em arquiteturas Serverless e integrações com IA.*
