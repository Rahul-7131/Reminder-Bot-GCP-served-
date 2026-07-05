# Reminder Bot (Telegram + Claude + GCP)

A personal agent that remembers dates you tell it about ("Aman's birthday is
1st September") and reminds you on Telegram the day before, every year.

## How it works

- You message the bot on Telegram → Telegram forwards it to `/webhook` on
  Cloud Run → Claude extracts the name/date → saved to Firestore.
- Cloud Scheduler hits `/check-reminders` once a day → checks Firestore for
  anything happening tomorrow → sends you a Telegram message if there's a match.

---

## 1. Create the Telegram bot

1. Open Telegram, search for **@BotFather**, start a chat.
2. Send `/newbot`, follow the prompts (choose a name and a username ending in `bot`).
3. BotFather gives you a **token** like `123456:ABC-DEF...`. Save it — this is `TELEGRAM_BOT_TOKEN`.

## 2. Set up the GCP project

```bash
gcloud auth login
gcloud projects create your-reminder-bot-id   # or use an existing project
gcloud config set project your-reminder-bot-id

# Enable required services
gcloud services enable run.googleapis.com firestore.googleapis.com \
  cloudscheduler.googleapis.com

# Create a Firestore database (Native mode)
gcloud firestore databases create --region=asia-south1   # pick a region near you
```

## 3. Get an Anthropic API key

Get one from the Claude Console (console.anthropic.com) — this is `ANTHROPIC_API_KEY`.

## 4. Deploy to Cloud Run

From inside this project folder:

```bash
gcloud run deploy reminder-bot \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars TELEGRAM_BOT_TOKEN=<your_token>,ANTHROPIC_API_KEY=<your_key>,SCHEDULER_SECRET=<make_up_a_random_string>
```

This builds the Dockerfile and deploys it. Note the **Service URL** it gives you,
e.g. `https://reminder-bot-xyz.a.run.app`.

## 5. Point Telegram at your webhook

```bash
curl "https://api.telegram.org/bot<your_token>/setWebhook?url=https://reminder-bot-xyz.a.run.app/webhook"
```

You should get `{"ok":true,"result":true,...}` back.

## 6. Message the bot once

Open Telegram, find your bot, send any message (e.g. "hi"). This registers your
`chat_id` as the "owner" in Firestore so reminders know where to go.

Then try: **"Aman's birthday is on 1st September"** — it should reply confirming
it saved it.

## 7. Set up the daily Cloud Scheduler job

```bash
gcloud scheduler jobs create http reminder-check \
  --schedule="0 9 * * *" \
  --uri="https://reminder-bot-xyz.a.run.app/check-reminders" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=<same_random_string_as_above>" \
  --location=asia-south1 \
  --time-zone="Asia/Kolkata"
```

This runs every day at 9am IST and checks if any event is happening tomorrow.

---

## Local testing (optional, before deploying)

```bash
pip install -r requirements.txt --break-system-packages
export TELEGRAM_BOT_TOKEN=<your_token>
export ANTHROPIC_API_KEY=<your_key>
export GOOGLE_APPLICATION_CREDENTIALS=<path_to_service_account_json>
python main.py
```

Use `ngrok http 8080` to get a public URL for testing the Telegram webhook locally.

## Extending this later

- Add a `/list` command to show all saved events.
- Add a `/delete <name>` command.
- Support reminders N days before (not just 1), configurable per event.
- Add recurring non-annual reminders (e.g. "remind me every Monday").
