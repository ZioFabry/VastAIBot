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
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS

# Load environment variables from the .env file
load_dotenv()

# Constants
VERSION = "1.0.6"
STATUS_FILE = "status.json"
CONFIG_FILE = "config.json"
RETRY_TIMEOUT = 15  # Retry timeout in seconds
REQUEST_DELAY = 2  # Delay between API requests
API_TIMEOUT = 10  # Timeout for API requests in seconds

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # Default to 300 seconds
VAST_URL = os.getenv("VAST_URL", "https://console.vast.ai/api/v0")
TELEGRAM_API_URL = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org") + "/bot"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class VastAIBot:
    def __init__(self):
        self.previous_status: Dict[str, Any] = {}
        self.vast_accounts: Dict[str, Any] = {}
        self.shutdown_event = asyncio.Event()
        self.bot: Optional[Bot] = None

        # Load InfluxDB parameters from .env
        self.influxdb_url = os.getenv("INFLUXDB_URL")
        self.influxdb_token = os.getenv("INFLUXDB_TOKEN")
        self.influxdb_org = os.getenv("INFLUXDB_ORG")
        self.influxdb_bucket = os.getenv("INFLUXDB_BUCKET")

        # Initialize InfluxDB client
        self.influx_client = influxdb_client.InfluxDBClient(
            url=self.influxdb_url,
            token=self.influxdb_token,
            org=self.influxdb_org,
        )
        self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)

    @staticmethod
    def load_json(file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logging.warning(f"JSON file not found: {file_path}")
            return {}
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON in file: {file_path}")
            return {}

    @staticmethod
    def save_json(file_path: str, data: Dict[str, Any]) -> None:
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            logging.error(f"Error saving JSON to {file_path}: {e}")

    @staticmethod
    def escape_markdown(text: str) -> str:
        escape_chars = r"_*[]()~`>#|+-={}.!"
        return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

    async def send_telegram_message(
        self, message: str, chat_ids: Optional[List[int]] = None
    ) -> None:
        recipients = {int(TELEGRAM_CHAT_ID)} if chat_ids is None else set(chat_ids)

        logging.info(f"Sending message to {recipients}:\n{message}")

        tasks = [
            self.bot.send_message(
                chat_id=chat_id,
                text=self.escape_markdown(message),
                parse_mode="MarkdownV2",
            )
            for chat_id in recipients
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # for chat_id in recipients:
        #     try:
        #         await self.bot.send_message(
        #             chat_id=chat_id,
        #             text=self.escape_markdown(message),
        #             parse_mode="MarkdownV2",
        #         )
        #     except Exception as e:
        #         logging.error(f"Error sending Telegram message to {chat_id}: {e}")

    async def call_vast_api(
        self, url: str, api_key: str, session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with session.get(
                url, headers=headers, timeout=API_TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logging.error(f"Error fetching {url}: {e}")
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON response from {url}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error: {traceback.format_exc()}")
        return {}

    async def get_server_status(
        self, api_key: str, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        data = await self.call_vast_api(f"{VAST_URL}/machines", api_key, session)
        return data.get("machines", [])

    async def get_current_user(
        self, api_key: str, session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        return await self.call_vast_api(f"{VAST_URL}/users/current", api_key, session)

    async def get_user_earnings(
        self, api_key: str, session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        return await self.call_vast_api(f"{VAST_URL}/user/earnings", api_key, session)

    def save_to_influxdb(
        self, account_name: str, server_id: str, server_data: Dict[str, Any]
    ) -> None:
        """
        Save numeric values of server data to InfluxDB.
        """
        points = []
        for key, value in server_data.items():
            if isinstance(value, (int, float)):  # Only save numeric values
                point = (
                    influxdb_client.Point("vastai")
                    .tag("account_name", account_name)
                    .tag("server_id", server_id)
                    .field(key, value)
                )
                points.append(point)

        try:
            self.write_api.write(
                bucket=self.influxdb_bucket, org=self.influxdb_org, record=points
            )
            logging.info(f"Data for server {server_id} saved to InfluxDB.")
        except Exception as e:
            logging.error(
                f"Failed to write data to InfluxDB for server {server_id}: {e}"
            )

    def save_earnings_to_influxdb(
        self, account_name: str, server_data: Dict[str, Any]
    ) -> None:
        """
        Save numeric values of server data to InfluxDB.
        """
        points = []
        for key, value in server_data.items():
            if isinstance(value, (int, float)):  # Only save numeric values
                point = (
                    influxdb_client.Point("vastai")
                    .tag("account_name", account_name)
                    .field(key, value)
                )
                points.append(point)

        try:
            self.write_api.write(
                bucket=self.influxdb_bucket, org=self.influxdb_org, record=points
            )
            logging.info(f"Data for account {account_name} saved to InfluxDB.")
        except Exception as e:
            logging.error(
                f"Failed to write data to InfluxDB for account {account_name}: {e}"
            )

    async def process_account(
        self,
        account_name: str,
        account_data: Dict[str, Any],
        session: aiohttp.ClientSession,
    ) -> None:
        first_run = False if self.previous_status else True

        messages: List[str] = []
        account_lines: List[str] = []
        changes_lines: List[str] = []

        changes_detected = False

        api_key = account_data["api_key"]
        notify = account_data["notify"]
        server_ids = account_data["machine_ids"]

        user = await self.get_current_user(api_key, session)
        balance: float = user.get("balance", 0)
        await asyncio.sleep(1)  # try to prevent too many requests response

        earnings = await self.get_user_earnings(api_key, session)
        machine_earnings = earnings.get("machine_earnings", 0) or 0.0

        # Save numeric values to InfluxDB
        self.save_earnings_to_influxdb(
            account_name, {"balance": balance, "machine_earnings": machine_earnings}
        )

        await asyncio.sleep(1)  # try to prevent too many requests response

        servers = await self.get_server_status(api_key, session)

        all_server: bool = True if -1 in server_ids else False

        for server in servers:
            server_id = str(server.get("id"))
            if not all_server and int(server_id) not in server_ids:
                continue

            listed: bool = server.get("listed", 0) or False
            running: int = server.get("current_rentals_running", 0)
            resident: int = server.get("current_rentals_resident", 0)
            rented: bool = running > 0
            reliability: float = server.get("reliability2", 0) or 0.0
            num_gpus: int = server.get("num_gpus", 0)
            earn_hour: float = server.get("earn_hour", 0) or 0.0
            earn_day: float = server.get("earn_day", 0) or 0.0
            gpu_occupancy: str = server.get("gpu_occupancy", "") or ""
            listed_gpu_cost: float = 0.0
            min_bid_price: float = 0.0
            listed_storage_cost: float = 0.0
            listed_inet_down_cost: float = 0.0
            listed_inet_up_cost: float = 0.0
            listed_min_gpu_count: int = 0
            num_reports: int = server.get("num_reports", "") or 0
            verification: str = server.get("verification", "None")

            min_bid_price: float = server.get("min_bid_price", 0) or 0.0

            if listed:
                rented_gpus = gpu_occupancy.count("D") + gpu_occupancy.count("I")
                listed_gpu_cost = server.get("listed_gpu_cost", 0) or 0.0
                listed_storage_cost = server.get("listed_storage_cost", 0) or 0.0
                listed_min_gpu_count = server.get("listed_min_gpu_count", 0) or 0
                listed_inet_down_cost = server.get("listed_inet_down_cost", 0) or 0.0
                listed_inet_up_cost = server.get("listed_inet_up_cost", 0) or 0.0
                price_info = f"💵{listed_gpu_cost:.2f} {min_bid_price:.2f} {listed_storage_cost:.2f}"
            else:
                rented_gpus = running
                price_info = "❌ NotList ❌"

            status_str = f"✅" if rented else "❌"
            gpu_status = f"{rented_gpus}/{num_gpus}"
            # earning_info = f"💰{earn_hour:.2f}$ / {earn_day:.2f}$"
            reliability_info = f"🎯{reliability*100:.2f}%"
            running_info = (f"🗄️{resident}" if resident > 0 else "") + (
                f"👤{running}" if rented else ""
            )
            server_line = f"🖥️{server_id} {status_str}{gpu_status}«{listed_min_gpu_count} {price_info} {reliability_info} {running_info}\n"

            old_data = self.previous_status.get(server_id)
            if old_data is not None:
                p_listed_gpu_cost = old_data.get("listed_gpu_cost") or 0.0
                p_listed_storage_cost = old_data.get("listed_storage_cost") or 0.0
                p_rented = old_data.get("rented") or False
                p_rented_gpus = old_data.get("rented_gpus") or 0
                p_min_bid_price = old_data.get("min_bid_price") or 0.0
                p_listed_min_gpu_count = old_data.get("listed_min_gpu_count") or 0.0
                p_num_reports = old_data.get("num_reports") or 0
                p_listed_inet_down_cost = old_data.get("listed_inet_down_cost") or 0.0
                p_listed_inet_up_cost = old_data.get("listed_inet_up_cost") or 0.0
                p_verification = old_data.get("verification", "")

                p_gpu_status = f"{p_rented_gpus}/{num_gpus}"

                if p_rented != rented or p_rented_gpus != rented_gpus:
                    changes_detected = True
                    ico_status = "🚀" if p_rented_gpus < rented_gpus else "🛬"
                    changes_lines.append(
                        f"{ico_status}{server_id} {status_str} {p_gpu_status} » {rented_gpus}/{num_gpus} = {(gpu_occupancy.replace(' ', ''))}\n"
                    )

                if p_listed_gpu_cost != listed_gpu_cost:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 💰 price change, {p_listed_gpu_cost:.4f}$ » {listed_gpu_cost:.4f}$\n"
                    )

                if p_listed_storage_cost != listed_storage_cost:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 💾 price change, {p_listed_storage_cost:.4f}$ » {listed_storage_cost:.4f}$\n"
                    )

                if p_listed_min_gpu_count != listed_min_gpu_count:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 🎞 min gpu change, {p_listed_min_gpu_count} » {listed_min_gpu_count}\n"
                    )

                if p_min_bid_price != min_bid_price:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 🪫 min bid change, {p_min_bid_price} » {min_bid_price}\n"
                    )
                if p_listed_inet_down_cost != listed_inet_down_cost:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 🌐 inet down change, {p_listed_inet_down_cost*1024.0:.2f}$ » {listed_inet_down_cost*1024.0:.2f}$\n"
                    )

                if p_listed_inet_up_cost != listed_inet_up_cost:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 🌐 inet up change, {p_listed_inet_up_cost*1024.0:.2f}$ » {listed_inet_up_cost*1024.0:.2f}$\n"
                    )

                if p_num_reports != num_reports:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 🚨 num reports change, {p_num_reports} » {num_reports}\n"
                    )
                if p_verification != verification:
                    changes_detected = True
                    changes_lines.append(
                        f"⚠️{server_id} 🔍 verification change, {p_verification} » {verification}\n"
                    )

            else:
                changes_detected = True

            self.previous_status[server_id] = {
                "rented": rented,
                "rented_gpus": rented_gpus,
                "listed_gpu_cost": listed_gpu_cost,
                "listed_storage_cost": listed_storage_cost,
                "min_bid_price": min_bid_price,
                "listed_min_gpu_count": listed_min_gpu_count,
                "earn_hour": earn_hour,
                "earn_day": earn_day,
                "reliability": reliability,
                "num_reports": num_reports,
                "gpu_occupancy": gpu_occupancy,
                "listed_inet_down_cost": listed_inet_down_cost,
                "listed_inet_up_cost": listed_inet_up_cost,
                "earn_hour": earn_hour,
                "earn_day": earn_day,
                "running": running,
                "resident": resident,
                "verification": verification,
            }

            # Save numeric values to InfluxDB
            self.save_to_influxdb(
                account_name, server_id, self.previous_status[server_id]
            )

            account_lines.append(server_line)

        if changes_lines:
            changes_lines.append(f"\n")

        if (first_run or changes_detected) and account_lines:
            messages.insert(
                0,
                f"👤 {account_name} 💰 {balance:.2f}$ 🏦 {machine_earnings:.2f}$\n\n"
                + "".join(changes_lines)
                + "".join(account_lines),
            )

            for message in messages:
                await self.send_telegram_message(message, notify)
        else:
            logging.info(f"👤 {account_name} No changes detected.")

    async def monitor_servers(self) -> None:
        async with aiohttp.ClientSession() as session:
            try:
                while not self.shutdown_event.is_set():
                    # Load the previous status and account data at each loop iteration to ensure they are up to date
                    self.previous_status = self.load_json(STATUS_FILE)
                    self.vast_accounts = self.load_json(CONFIG_FILE)

                    for account_name, account_data in self.vast_accounts.items():
                        await self.process_account(account_name, account_data, session)

                        # try to prevent too many requests response
                        await asyncio.sleep(2)

                    self.save_json(STATUS_FILE, self.previous_status)

                    logging.info(
                        f"Loop completed. Next loop in {CHECK_INTERVAL} seconds."
                    )
                    try:
                        await asyncio.wait_for(
                            self.shutdown_event.wait(), timeout=CHECK_INTERVAL
                        )
                    except asyncio.TimeoutError:
                        continue
            finally:
                await session.close()

    def handle_shutdown(self) -> None:
        logging.info("Shutdown signal received.")
        self.shutdown_event.set()

    async def main(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.handle_shutdown)

        async with Bot(token=TELEGRAM_BOT_TOKEN, base_url=TELEGRAM_API_URL) as bot:
            self.bot = bot
            await self.send_telegram_message(f"🟢 VastAIBot v{VERSION}")
            try:
                await self.monitor_servers()
            finally:
                await self.send_telegram_message(f"🔴 VastAIBot v{VERSION}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )
    bot = VastAIBot()
    asyncio.run(bot.main())
