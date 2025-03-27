import os
import json
import asyncio
import aiohttp
import logging
import re
import signal
import traceback

from dotenv import load_dotenv
from telegram import Bot
from typing import List, Dict, Any, Optional

# Load environment variables from the .env file
load_dotenv()

# Define paths for status and configuration files
STATUS_FILE = "status.json"
CONFIG_FILE = "config.json"

# Retrieve necessary environment variables
VAST_URL = os.getenv("VAST_URL")  # Vast.ai API URL
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL"))  # Check interval in seconds
TELEGRAM_API_URL = os.getenv("TELEGRAM_API_URL") + "/bot"  # Telegram API URL
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Telegram bot token
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Telegram chat ID for admin

# Global dictionary to store Vast.ai account configurations
vast_accounts: Dict[str, Any] = {}
previous_status: Dict[str, Any] = {}


# Function to load account configurations from a JSON file
def load_json(file_path: str) -> Dict[str, Any]:
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning(f"JSON file not found: {file_path}")
        return {}
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in config file: {file_path}")
        return {}


# Function to save current server status to a JSON file
def save_json(file_path: str, data: Dict[str, Any]) -> None:
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        logging.error(f"Error saving status to {file_path}: {e}")


# Function to escape special Markdown characters for Telegram messages
def escape_markdown(text: str) -> str:
    escape_chars = r"_*[]()~`>#|+-={}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


# Asynchronous function to send a Telegram message
async def send_telegram_message(
    message: str, chat_ids: Optional[List[int]] = None
) -> None:
    """
    avoid/allow to send messages to the users during development
    """
    recipients = set(chat_ids) if chat_ids else set()
    # recipients = set()

    recipients.add(int(TELEGRAM_CHAT_ID))

    logging.info(
        f"Sending message to [" + ", ".join(map(str, recipients)) + f"]:\n{message}"
    )

    for chat_id in recipients:
        try:
            await bot.send_message(
                chat_id=chat_id, text=escape_markdown(message), parse_mode="MarkdownV2"
            )
        except Exception as e:
            logging.error(f"Error sending Telegram message to {chat_id}: {e}")


# Asynchronous function to get server status from Vast.ai
async def get_server_status(
    api_key: str, session: aiohttp.ClientSession
) -> List[Dict[str, Any]]:
    url = f"{VAST_URL}/machines"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with session.get(url, headers=headers, timeout=10) as response:
            response.raise_for_status()
            data = await response.json()
            return data.get("machines", [])
    except aiohttp.ClientError as e:
        logging.error(f"Error fetching server status: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON response from Vast.ai: {e}")
        return []


# Asynchronous function to get current user information from Vast.ai
async def get_current_user(
    api_key: str, session: aiohttp.ClientSession
) -> Dict[str, Any]:
    await asyncio.sleep(1)

    url = f"{VAST_URL}/users/current"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with session.get(url, headers=headers, timeout=10) as response:
            response.raise_for_status()
            return await response.json()
    except aiohttp.ClientError as e:
        logging.error(f"Error fetching user info: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON user response: {e}")
        return []


# Main asynchronous function to monitor servers
async def monitor_servers() -> None:
    """
    Asynchronously monitors the status of servers from Vast.ai, compares it with the previous status,
    and sends Telegram messages for any detected changes.
    """
    global previous_status

    # Enable first_run logic only when the previous status dictionary is empty,
    #
    first_run = False if previous_status else True

    async with aiohttp.ClientSession() as session:
        while not shutdown_event.is_set():
            account_items = list(vast_accounts.items())

            for index, (account_name, account_data) in enumerate(account_items):
                messages: List[str] = []
                notify: List[int] = []
                account_lines: List[str] = []
                changes_lines: List[str] = []

                changes_detected = False

                api_key = account_data["api_key"]
                notify = account_data["notify"]
                server_ids = account_data["machine_ids"]

                user = await get_current_user(api_key, session)
                balance = user.get("balance", 0)

                servers = await get_server_status(api_key, session)

                all_server: bool = True if -1 in server_ids else False

                for server in servers:
                    server_id = str(server.get("id"))
                    if all_server or int(server_id) in server_ids:
                        listed = server.get("listed", 0)
                        running = server.get("current_rentals_running", 0)
                        rented = running > 0
                        reliability = server.get("reliability2", 0) or 0.0
                        total_gpus = server.get("num_gpus", 0)
                        earn_hour = server.get("earn_hour", 0) or 0.0
                        earn_day = server.get("earn_day", 0) or 0.0

                        price: float = 0.0
                        minbid: float = 0.0
                        hdprice: float = 0.0
                        mingpu: int = 0

                        if listed:
                            rented_gpus = server.get("gpu_occupancy", "").count(
                                "D"
                            ) + server.get("gpu_occupancy", "").count("I")
                            price = server.get("listed_gpu_cost", 0) or 0.0
                            minbid = server.get("min_bid_price", 0) or 0.0
                            hdprice = server.get("listed_storage_cost", 0) or 0.0
                            mingpu = server.get("listed_min_gpu_count", 0) or 0
                            price_info = f"💵{price:.2f}/{minbid:.2f} 💾{hdprice:.2f}"
                        else:
                            rented_gpus = running
                            price_info = "❌ NotList ❌"

                        status_str = "✅Rent" if rented else "❌Free"
                        gpu_status = f"🎞{rented_gpus}/{total_gpus}"
                        earning_info = f"💰{earn_hour:.2f}$ / {earn_day:.2f}$"
                        reliability_info = f"🎯{reliability*100:.2f}%"
                        server_line = f"🖥️{server_id} {status_str} {gpu_status}»{mingpu} {price_info} {reliability_info}\n"

                        old_data = previous_status.get(server_id)
                        if old_data is not None:
                            p_price = old_data.get("price") or 0.0
                            p_hdprice = old_data.get("hdprice") or 0.0
                            p_rented = old_data.get("rented") or False
                            p_rented_gpus = old_data.get("rented_gpus") or 0
                            p_minbid = old_data.get("minbid") or 0.0
                            p_mingpu = old_data.get("mingpu") or 0.0

                            p_gpu_status = f"🎞{p_rented_gpus}/{total_gpus}"

                            if p_rented != rented or p_rented_gpus != rented_gpus:
                                changes_detected = True
                                ico_status = (
                                    "🚀" if p_rented_gpus < rented_gpus else "🛬"
                                )
                                changes_lines.append(
                                    f"{ico_status} {server_id} {status_str} {p_gpu_status} -> {gpu_status}\n"
                                )

                            if p_price != price:
                                changes_detected = True
                                changes_lines.append(
                                    f"⚠️ {server_id} 🎞 price change, {p_price:.4f}$ -> {price:.4f}$\n"
                                )

                            if p_hdprice != hdprice:
                                changes_detected = True
                                changes_lines.append(
                                    f"⚠️ {server_id} 💾 price change, {p_hdprice:.4f}$ -> {hdprice:.4f}$\n"
                                )

                            if p_mingpu != mingpu:
                                changes_detected = True
                                changes_lines.append(
                                    f"⚠️ {server_id} #️⃣ min gpu change, {p_mingpu} -> {mingpu}\n"
                                )

                            if p_minbid != minbid:
                                changes_detected = True
                                changes_lines.append(
                                    f"⚠️ {server_id} #️⃣ min bid change, {p_minbid} -> {minbid}\n"
                                )
                        else:
                            changes_detected = True

                        previous_status[server_id] = {
                            "rented": rented,
                            "rented_gpus": rented_gpus,
                            "price": price,
                            "hdprice": hdprice,
                            "minbid": minbid,
                            "mingpu": mingpu,
                            "earn_hour": earn_hour,
                            "earn_day": earn_day,
                            "reliability": reliability,
                        }
                        account_lines.append(server_line)

                if changes_lines:
                    changes_lines.append(f"\n")

                if (first_run or changes_detected) and account_lines:
                    messages.insert(
                        0,
                        f"👤 {account_name} 💰 {balance:.2f}$\n\n"
                        + "".join(changes_lines)
                        + "".join(account_lines),
                    )

                    for message in messages:
                        await send_telegram_message(message, notify)
                else:
                    logging.info(f"👤 {account_name} No changes detected.")

                if index < len(account_items) - 1:
                    await asyncio.sleep(2)  # try to prevent too many requests response

            first_run = False

            save_json(STATUS_FILE, previous_status)

            logging.info(f"Loop completed. Next looop in {CHECK_INTERVAL} seconds")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=CHECK_INTERVAL)
            except asyncio.TimeoutError:
                continue


def handle_shutdown() -> None:
    """
    Handles the shutdown signal by logging a message and setting the shutdown event.
    """
    logging.info("shutdown...")
    shutdown_event.set()


async def main() -> None:
    """
    Main asynchronous function that orchestrates the server monitoring process.
    It initializes the bot, sets up signal handlers, loads configurations,
    starts the monitoring loop, and handles shutdown.
    """
    global previous_status

    loop = asyncio.get_running_loop()
    # Setup signal handlers for graceful shutdown on SIGINT and SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown)

    # Send a Telegram message indicating the bot is online.
    await send_telegram_message("🟢 VastAIBot **Online**")

    # Main monitoring loop
    while not shutdown_event.is_set():
        try:
            # Monitor the servers and handle any changes.
            await monitor_servers()
        except Exception as e:
            # Log any exceptions that occur during monitoring.
            logging.error(traceback.format_exc())
            # Wait for 15 seconds before retrying or shutdown.
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue

        # Save the current server status to the status file.
        save_json(STATUS_FILE, previous_status)

    # Send a Telegram message indicating the bot is offline.
    await send_telegram_message("🔴 VastAIBot **Offline**")


# Initialize the shutdown event.
shutdown_event = asyncio.Event()

# Initialize the Telegram Bot with the provided token & api url.
bot = Bot(token=TELEGRAM_BOT_TOKEN, base_url=TELEGRAM_API_URL)

# Configure logging to output messages to the console.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Load the previous server status from the status file.
previous_status = load_json(STATUS_FILE)

# Load the Vast.ai account configurations from the config file.
vast_accounts = load_json(CONFIG_FILE)

# Entry point of the script.
if __name__ == "__main__":
    # Run the main asynchronous function.
    asyncio.run(main())
