# VastAIBot

VastAIBot is a Python-based monitoring tool that tracks the status of your rented servers on [Vast.ai](https://vast.ai) and sends updates via Telegram. It provides real-time notifications about server status changes, pricing updates, and other relevant metrics.

## Features

- Monitors multiple Vast.ai accounts and their associated servers.
- Sends real-time notifications to a Telegram chat or group.
- Tracks server metrics such as rental status, GPU usage, pricing, and reliability.
- Logs all activities for debugging and auditing purposes.
- Automatically restarts on failure to ensure continuous monitoring.

## Prerequisites

Before running VastAIBot, ensure you have the following:

1. **Python 3.8+** installed on your system.
2. Required Python packages listed in `requirements.txt`.
3. A Telegram bot token and chat ID for notifications.
4. API keys for your Vast.ai accounts.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/VastAIBot.git
   cd VastAIBot
   ```

2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure the environment variables:
   - Copy `.env.sample` to `.env`:
     ```bash
     cp .env.sample .env
     ```
   - Edit .env and provide the required values:
     ```env
     VAST_URL=https://console.vast.ai/api/v0
     TELEGRAM_API_URL=https://api.telegram.org:443
     TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
     TELEGRAM_CHAT_ID=<your-telegram-chat-id>
     CHECK_INTERVAL=300
     ```

4. Configure your Vast.ai accounts:
   - Copy config.json.sample to config.json:
     ```bash
     cp config.json.sample config.json
     ```
   - Edit config.json to include your Vast.ai API keys, machine IDs, and notification chat IDs:
     ```json
     {
         "Account1": {
             "api_key": "<account1_api_key>",
             "machine_ids": [12345, 23456],
             "notify": [12345678, 87654321]
         },
         "Account2": {
             "api_key": "<account2_api_key>",
             "machine_ids": [987654, 876543],
             "notify": [12345678, 87654321]
         }
     }
     ```

## Usage

### Starting the Bot

You can run the Python script directly:
```bash
python3 VastAIBot.py 2>&1 | tee -a log/VastAIBot.log
```

### Logs

Logs are stored in the log directory. The main log file is VastAIBot.log.

## How It Works

1. **Configuration Loading**:
   - The bot reads environment variables from .env.
   - Account configurations are loaded from config.json.

2. **Monitoring**:
   - The bot periodically fetches server status from Vast.ai using the API.
   - It compares the current status with the previous state stored in status.json.

3. **Notifications**:
   - If changes are detected (e.g., server rented, price updated), the bot sends a Telegram message.

4. **Logging**:
   - All activities are logged for debugging and auditing.

## Environment Variables

| Variable             | Description                                      |
|----------------------|--------------------------------------------------|
| `VAST_URL`           | Base URL for the Vast.ai API.                    |
| `TELEGRAM_API_URL`   | Base URL for the Telegram API.                   |
| `TELEGRAM_BOT_TOKEN` | Token for your Telegram bot.                     |
| `TELEGRAM_CHAT_ID`   | Chat ID where notifications will be sent.        |
| `CHECK_INTERVAL`     | Interval (in seconds) between status checks.     |

## Configuration File (`config.json`)

| Key          | Description                                      |
|--------------|--------------------------------------------------|
| `api_key`    | API key for the Vast.ai account.                 |
| `machine_ids`| List of server IDs to monitor. Use `-1` for all. |
| `notify`     | List of Telegram chat IDs to notify.             |

## Logging

- Logs are stored in the log directory.
- The main log file is VastAIBot.log.
- Rember to configure logrotate to rotate, compress and store as `.gz` files, for example you can create the file /etc/logrotate.d/VastAIBot.log with:
  ```
  # adjust the path if needed
  ~/VastAIBot/log/*.log {
     daily
     rotate 30
     compress
     notifempty
     missingok
     copytruncate
  }
  ```

## Troubleshooting

1. **Bot not sending messages**:
   - Ensure the Telegram bot token and chat ID are correct in .env.
   - Check the logs for errors.

2. **No status updates**:
   - Verify the Vast.ai API keys in config.json.
   - Ensure the server IDs are correct.

3. **Script crashes**:
   - Check the logs for stack traces.
   - Ensure all dependencies are installed.

## License

This project is licensed under the GNU General Public License v3.0.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## Acknowledgments

- [Vast.ai](https://vast.ai) for their API.
- [Telegram](https://core.telegram.org/bots) for their bot platform.
