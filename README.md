# Reminder Bot (Telegram + OpenAI + GCP)

A personal Telegram bot that remembers annual dates like birthdays and
anniversaries, plus one-time reminders like trains, appointments, bills, and
meetings.

## How It Works

- You message the bot on Telegram.
- Telegram forwards the message to `/webhook` on Cloud Run.
- The bot tries a local rule-based parser first for common messages.
- If needed, it calls OpenAI to parse the message into a structured action.
- Reminders are stored in Firestore.
- Cloud Scheduler calls `/check-reminders` once a day and the bot sends matching
  reminders for today.

## 1. Create The Telegram Bot

1. Open Telegram, search for **@BotFather**, and start a chat.
2. Send `/newbot` and follow the prompts.
3. Save the bot token. This is `TELEGRAM_BOT_TOKEN`.

## 2. Set Up The GCP Project

```bash
gcloud auth login
gcloud projects create your-reminder-bot-id
gcloud config set project your-reminder-bot-id

gcloud services enable run.googleapis.com firestore.googleapis.com \
  cloudscheduler.googleapis.com

gcloud firestore databases create --region=asia-south1
```

## 3. Configure Parser API Keys

Create an OpenAI API key from the OpenAI platform dashboard. This is
`OPENAI_API_KEY`.

Optional variables:

- `OPENAI_MODEL` defaults to `gpt-4.1-mini`.
- `GEMINI_API_KEY` can still be set as a fallback if you want Gemini available.
- `BOT_TIMEZONE` defaults to `Asia/Kolkata`.

The bot tries the local parser before making any model call, so common messages
like `Rahul bday 2 July`, `Doctor appointment tomorrow`, `Show July reminders`,
and `What's next?` can work without using model quota.

## 4. Deploy To Cloud Run

```bash
gcloud run deploy reminder-bot \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars TELEGRAM_BOT_TOKEN=<your_token>,OPENAI_API_KEY=<your_openai_key>,SCHEDULER_SECRET=<make_up_a_random_string>
```

Note the service URL, for example:

```text
https://reminder-bot-xyz.a.run.app
```

## 5. Point Telegram At Your Webhook

```bash
curl "https://api.telegram.org/bot<your_token>/setWebhook?url=https://reminder-bot-xyz.a.run.app/webhook"
```

## 6. Try The Bot

Message the bot once so it can save your chat id, then try:

- `Rahul bday 2 July`
- `Doctor appointment tomorrow`
- `Remind me to catch the train on 3 June`
- `Rahul birthday is actually on 3 July`
- `Show July reminders`
- `What's next?`

Commands:

- `/list` shows every saved reminder.
- `/delete <name>` deletes a saved reminder.
- `/help` shows help text.

## 7. Set Up The Daily Scheduler

```bash
gcloud scheduler jobs create http reminder-check \
  --schedule="0 9 * * *" \
  --uri="https://reminder-bot-xyz.a.run.app/check-reminders" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=<same_random_string_as_above>" \
  --location=asia-south1 \
  --time-zone="Asia/Kolkata"
```

## Local Testing

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=<your_token>
export OPENAI_API_KEY=<your_openai_key>
export OPENAI_MODEL=gpt-4.1-mini
export GOOGLE_APPLICATION_CREDENTIALS=<path_to_service_account_json>
python main.py
```

Use `ngrok http 8080` to test the Telegram webhook locally.
