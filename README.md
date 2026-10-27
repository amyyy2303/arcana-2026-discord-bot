# 🏆 ARCANA 2026 — Discord Cipher Competition Bot

<p align="center">
  <strong>A Discord bot built to manage a competitive cipher-solving event.</strong>
  <br />
  Team-based competition • Automated scoring • Private team channels • Live leaderboard
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.x-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Discord-Bot-5865F2?logo=discord&logoColor=white" alt="Discord" />
  <img src="https://img.shields.io/badge/Docker-Containerized-2496ED?logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/Status-Competition%20Project-orange" alt="Project Status" />
</p>

---

## 📖 Overview

**Arcana 2026** is a Discord-based cipher competition management bot designed to organize and run a team-based puzzle-solving event.

It brings competition operations into Discord by providing team-oriented channels, cipher challenges, automated score management, answer submission, pass mechanics, and leaderboard functionality.

The goal is to reduce manual event administration and give participants a structured environment in which to solve challenges and compete.

## ✨ Features

### 🧩 Cipher Challenge System
- Organizes cipher challenges using the project's cipher data and image assets.
- Supports different difficulty levels: Easy, Medium, and Hard.
- Allows participants to submit answers through bot commands.
- Includes a configurable question and challenge management system.

### 👥 Team Management
- Supports multiple competition teams.
- Provides team-specific channels for competition activities.
- Includes functionality for event setup and team management.
- Helps separate team discussions within the Discord server.

### 🏅 Automated Scoring
The configured scoring system awards points based on challenge difficulty:

| Difficulty | Points |
|:---|---:|
| Easy | +150 |
| Medium | +250 |
| Hard | +400 |

Additional scoring mechanics include:
- Incorrect answer penalty: **−12 points**
- Maximum attempts: **4**
- Passing a challenge: **+20 points to eligible opposing teams**

Scoring and challenge behavior are implemented in the bot's event logic. Review the source code before changing competition rules.

### 📊 Leaderboard
- Tracks team scores.
- Displays competition rankings.
- Supports leaderboard updates through the bot's commands.

### ⚙️ Event Administration
- Event setup functionality.
- Team and channel configuration.
- Administrative and server-management commands.
- Command handling through the bot's loaded extensions.

### 🐳 Docker Support
- Containerized bot execution.
- Docker Compose-based lifecycle management.
- Persistent local data directory mounting.
- Separate test service configuration.

---

## 🛠️ Technology Stack

| Technology | Purpose |
|:---|:---|
| Python | Bot application and event logic |
| Discord API | Server interaction and bot commands |
| discord.py-compatible extensions | Command and cog architecture |
| SQLite | Local competition database |
| JSON | Cipher and challenge data |
| Docker | Containerized execution |
| Docker Compose | Service orchestration |
| pytest | Automated testing |

---

## 📂 Project Structure

```text
discord-bot/
├── bot.py
├── cogs/
│   ├── cipher_event.py
│   ├── general.py
│   ├── json_tools.py
│   ├── links.py
│   ├── server_management.py
│   └── teams.py
├── database/
│   └── db.py
├── data/
│   ├── ciphers.json
│   └── ciphers/
├── scripts/
│   ├── generate_ciphers.py
│   ├── test_bot_setup.py
│   ├── test_cipher_limits.py
│   └── test_encryption_and_hiding.py
├── tests/
│   ├── test_cipher_event.py
│   └── test_scoring_guards.py
├── utils/
│   ├── embeds.py
│   ├── json_utils.py
│   └── security.py
├── Dockerfile
├── compose.yaml
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .dockerignore
└── .gitignore
```

---

## 🚀 Getting Started

### Prerequisites

Before running the bot, make sure you have:

- Python installed if running locally.
- Docker Desktop installed if using containers.
- A Discord application and bot created through the Discord Developer Portal.
- The required bot token and configuration values.
- Access to a Discord server where the bot can be installed.

### 1. Clone the repository

```bash
git clone https://github.com/amyyy2303/arcana-2026-discord-bot.git
cd arcana-2026-discord-bot
```

### 2. Configure environment variables

Create a local `.env` file using the configuration expected by the application.

```bash
touch .env
```

Open `.env` in your editor and add the required configuration values. Check `bot.py` and related source files for the exact environment variable names expected by this project.

**Never commit your real bot token, credentials, or other secrets.**

### 3. Run with Docker Compose

Make sure Docker Desktop is running, then execute:

```bash
docker compose config --quiet
docker compose up -d --build discord-bot
```

Check the container status:

```bash
docker compose ps
```

View bot logs:

```bash
docker compose logs -f discord-bot
```

Press `Ctrl+C` to stop following the logs. This does not stop the bot container.

### 4. Run locally without Docker

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

After configuring the required environment variables, run:

```bash
python bot.py
```

The bot must have valid Discord credentials and the necessary server permissions to connect and operate.

---

## 🧪 Testing

Install the development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the test suite:

```bash
python -m pytest -q
```

If using the Docker Compose test service, run:

```bash
docker compose --profile test run --build --rm test
```

Review the test configuration before executing it against any database containing live competition data.

---

## 🛑 Useful Docker Commands

Run these commands from the project directory.

| Action | Command |
|:---|:---|
| Start the bot | `docker compose up -d discord-bot` |
| Rebuild and start | `docker compose up -d --build discord-bot` |
| Stop the bot | `docker compose stop discord-bot` |
| Restart the bot | `docker compose restart discord-bot` |
| View logs | `docker compose logs -f discord-bot` |
| Check status | `docker compose ps` |
| Run tests | `docker compose --profile test run --build --rm test` |

To shut down Docker Desktop, stop your containers first and then quit Docker Desktop normally.

---

## 🔐 Discord Setup and Security

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create and configure its bot user.
3. Store the bot token in the local environment configuration required by the application.
4. Invite the bot to the intended Discord server with the permissions required by its features.
5. Enable the necessary gateway intents in the Developer Portal if the code requires them.
6. Grant channel-management permissions only if the bot needs to create or configure team channels.
7. Keep tokens, credentials, local databases, and private configuration out of Git.
8. Restrict access to unreleased cipher images, answers, and competition data.

Never share your bot token publicly. If it is exposed, regenerate it through the Discord Developer Portal.

---

## 🧠 Competition Rules

The current implementation includes difficulty-based scoring, penalties for incorrect answers, a limited number of attempts, and points associated with passing challenges.

The values documented above reflect the configured scoring behavior described in this project. Consult `cogs/cipher_event.py` before modifying rules or deploying a new competition configuration.

Use a test Discord server when validating commands that affect scores, attempts, challenge queues, or team state.

---

## 🗺️ Future Improvements

Potential improvements for future versions include:

- A dedicated event administration dashboard.
- More detailed competition analytics and score history.
- Configurable competition rules.
- Improved event monitoring and operational logging.
- Expanded automated tests and deployment checks.
- Safer backup and restoration workflows.
- More granular team and administrator permissions.

These are possible future enhancements, not claims about currently implemented functionality.

---

## 🤝 Contributing

Contributions and improvements are welcome.

1. Fork the repository or create a feature branch.
2. Make your changes.
3. Test the changes before submitting them.
4. Open a pull request describing the changes.

Keep secrets and live competition data out of commits.

---

## 📄 License

No license has been specified yet. Until a license is added, do not assume that the repository grants permission to reuse, redistribute, or modify its contents.

---

## 🔗 Repository

**GitHub:** https://github.com/amyyy2303/arcana-2026-discord-bot

<p align="center">
  <strong>ARCANA 2026 — Decode the Cipher. Climb the Leaderboard. Claim the Victory.</strong>
</p>
