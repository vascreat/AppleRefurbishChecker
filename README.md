Telegram Keyword Monitor Bot

Overview
This project provides a Telegram bot that lets users create monitoring tasks for web pages and receive alerts when chosen keywords appear.

Security Note
Do not hardcode your bot token in source code. This project reads the token from environment variables.

Token Placeholder
Use this placeholder value format for local testing setup:
BOT_TOKEN=[8566527550:AAHWWdkZZjMDw2D3QlEM2IiMDE44xMA9DWs]

Features
- Create, configure, run, stop, list, and delete named tasks.
- Persist tasks in SQLite so they survive restarts.
- Keep tasks during container updates via persistent storage + startup migration.
- Create rolling DB backups before migration (keeps latest 10 backups).
- Run asynchronous background monitoring loops.
- Detect keywords case-insensitively inside a single item block.
- Optional item-level price range filtering.
- Notify the task creator's chat when matches are found with direct product link.

Task Model
Each task stores:
- Task name (unique)
- Creator (Telegram user ID)
- Creator chat ID
- Target URL
- Keywords list
- Min price (optional)
- Max price (optional)
- Check interval (minutes)
- Status (running or stopped)

Commands
- /task <task_name>
  Creates a new task with default values.
- /checklink <task_name> <url>
  Sets the URL for a task after URL validation.
- /search <task_name> <keyword1, keyword2, ...>
  Adds keywords without duplicates.
- /price <task_name> <min_price> <max_price>
  Sets item price range filter. Item must fall inside this range.
- /interval <task_name> <minutes>
  Sets interval. Default 30, min 10, max 720.
- /start <task_name>
  Starts monitoring if URL and keywords exist.
- /stop <task_name>
  Stops monitoring.
- /rm <task_name>
  Deletes task permanently.
- /list
  Lists all current tasks and their configuration.
- /mytasks
  Lists only tasks created by the user who runs the command.

Project Structure
- main.py: Entrypoint.
- app/config.py: Environment and constants.
- app/storage.py: SQLite task persistence.
- app/monitor.py: Async page polling and notification delivery.
- app/handlers.py: Telegram command handlers and validation.
- app/bot_app.py: Application bootstrap and lifecycle hooks.

Install and Run (Local)
1. Create and activate a virtual environment.
2. Install dependencies:
   pip install -r requirements.txt
3. Set environment variables:
   PowerShell:
   $env:BOT_TOKEN="your_real_bot_token"
   Optional custom DB path:
   $env:TASKS_DB_PATH="data/tasks.db"
4. Run the bot:
   python main.py

Docker
Build image:
- docker build -t telegram-bot .

Run container:
- docker run -d --name telegram-bot -e BOT_TOKEN=your_token -v ${PWD}/data:/app/data telegram-bot

Run with docker-compose:
- docker-compose up -d

Docker Persistence
Task data is stored at /app/data/tasks.db inside the container.
The compose file mounts ./data to /app/data so tasks persist across restarts.

Update-Safe Task Persistence
- On startup, the bot automatically creates a backup of the existing SQLite DB before running migrations.
- Backups are saved under data/backups with timestamped filenames.
- The bot retains the latest 10 backups automatically.
- Existing tasks are carried forward to new bot versions unless you manually delete data/tasks.db.

Recommended Update Flow (No Task Loss)
1. Pull or edit new code.
2. Rebuild and restart:
  docker compose up -d --build
3. Task data remains in data/tasks.db and is reused by the new container.

How Monitoring Works
- The bot fetches each running task URL at configured intervals.
- It scans candidate item blocks (products/cards/tiles) on the page.
- All configured keywords must match in the same item block.
- If price range is configured, that same item must include a price in range.
- On match, it sends a notification with:
  - Creator mention
  - Item title
  - Item price
  - Direct buy link for the matched item
  - Message: The item you are searching for is available

Error Handling
- Invalid URL input is rejected.
- Missing command parameters return usage hints.
- Non-existing tasks return clear errors.
- Incomplete tasks cannot be started.
- Network failures are retried and logged.

How to Add a New Command
1. Open app/handlers.py.
2. Add a new async command function:
   async def my_command(update, context):
       ...
3. Register it in register_handlers with CommandHandler.
4. If it needs storage or monitoring, use _get_services(context).
5. Add the new command to this README.

How to Add New Features (Example: New Notification Type)
1. Open app/monitor.py.
2. Add a new sender method (for example, webhook, email, or SMS).
3. Call the sender method inside _send_notification.
4. Add any configuration variables in app/config.py.
5. Document setup changes in README.
