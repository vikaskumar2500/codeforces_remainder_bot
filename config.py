# config.py
import os
import logging # Optional: for logging if the token is not found

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if TELEGRAM_BOT_TOKEN is None:
    # This message will appear in your logs if the bot starts without the token being set.
    # On a deployment platform, this means you forgot to set the environment variable.
    # Locally, this means you need to set it in your shell or .env file.
    logger.warning(
        "TELEGRAM_BOT_TOKEN environment variable not found! "
        "The bot will not be able to connect to Telegram."
    )
    # You might even want to raise an error here or have main() exit if it's critical
    # raise ValueError("TELEGRAM_BOT_TOKEN not set. Bot cannot start.")