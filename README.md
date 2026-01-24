# discipline_bot

Telegram bot for discipline training and weight tracking.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create `.env` from `.env.example` and set `BOT_TOKEN`.

```bash
cp .env.example .env
```

3. Run the bot:

```bash
python -m app.main
```

## Environment variables

Example `.env`:

```
BOT_TOKEN=your_telegram_bot_token
DB_PATH=/absolute/path/to/discipline_bot/data/discipline_bot.sqlite3
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO
```

## Deployment (systemd)

Create a unit file, for example `/etc/systemd/system/discipline_bot.service`:

```
[Unit]
Description=Discipline Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/discipline_bot
Environment="PATH=/path/to/discipline_bot/.venv/bin"
ExecStart=/path/to/discipline_bot/.venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable discipline_bot
sudo systemctl start discipline_bot
sudo systemctl status discipline_bot
```
