# Steam Anime Telegram Bot

![Preview](assets/preview_gh.png)

A Telegram bot for tracking new anime game and demo 
releases on Steam, with daily AI-powered 
summary reporting on newly released games and offering 
smart recommendations.

## Built with
- [python-telegram-bot](https://python-telegram-bot.org/)
- [Mistral AI](https://mistral.ai/) (AI summaries)
- Docker & Docker Compose

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
AI_KEY=your_google_ai_key
CHECK_INTERVAL_MINUTES=60

3. Build and launch container:
```bash
docker compose up --build
```
