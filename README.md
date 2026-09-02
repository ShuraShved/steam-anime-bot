# Steam Anime Telegram Bot

<p align="center">
  <img src="assets/preview_gh.png"/>
</p>

A Telegram bot for tracking new anime game and demo 
releases on Steam, with daily AI-powered 
summary reporting on newly released games and offering 
smart recommendations.

**Email Digests [NEW!]:** Users can now link their email to receive daily summaries straight to their inbox.

## Built with
* **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** – Telegram API framework
* **[Mistral API](https://mistral.ai/)** – AI-generated daily summaries and recommendations
* **Google SMTP** – Sending automated daily digests to user emails
* **[Docker & Docker Compose](https://www.docker.com/)** – Containerization and deployment

## Setup and Launch

1. **Clone the repository:**
```bash
git clone https://github.com/ShuraShved/steam-anime-bot.git
cd steam-anime-bot
```

2. **Configuration:**

Before launching, you need to set up your environment 
variables. Create a .env file in the root directory 
and add your API tokens:

BOT_TOKEN=your_telegram_bot_token

AI_KEY=your_mistralai_key

CHECK_INTERVAL_MINUTES=60

SMTP_HOST=smtp.gmail.com

SMTP_PORT=465

SMTP_USER=your@gmail.com

SMTP_PASSWORD="your google app password"

SMTP_FROM=your@gmail.com

3. **Build and launch container:**
```bash
docker compose up --build
```
> [!TIP]
> Add the -d flag to run the container in the background.
