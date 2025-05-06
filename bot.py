
import logging
import json
import os
from datetime import datetime, timedelta, timezone
import tempfile # Added for robust file saving

import requests
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, filters
from telegram.constants import ParseMode
from apscheduler.schedulers.background import BackgroundScheduler

from dotenv import load_dotenv
load_dotenv() # This loads variables from .env into the environment
# Local import
from config import TELEGRAM_BOT_TOKEN


# --- Configuration ---
SUBSCRIBERS_FILE = "subscribers.json"
CODEFORCES_API_URL = "https://codeforces.com/api/contest.list?gym=false"
REMINDER_INTERVALS = {
    "24h": timedelta(hours=24),
    "1h": timedelta(hours=1),
    "15m": timedelta(minutes=15),
}
SCHEDULER_CHECK_INTERVAL_HOURS = 4

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Subscriber Management ---
def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                data = json.load(f)
                if not isinstance(data, list): # Basic validation
                    logger.warning(f"{SUBSCRIBERS_FILE} does not contain a list. Initializing empty.")
                    return set()
                return set(data)
        except json.JSONDecodeError:
            logger.error(f"Error decoding {SUBSCRIBERS_FILE}. Starting with empty subscribers.")
            return set()
        except OSError as e:
            logger.error(f"OSError loading subscribers from {SUBSCRIBERS_FILE}: {e}. Starting with empty.", exc_info=True)
            return set()
        except Exception as e:
            logger.error(f"Unexpected error loading subscribers from {SUBSCRIBERS_FILE}: {e}. Starting with empty.", exc_info=True)
            return set()
    logger.info(f"{SUBSCRIBERS_FILE} not found. Starting with empty subscribers.")
    return set()

# def save_subscribers(subscribers_set):
#     # Use a temporary file for writing to make the save atomic
#     # Ensure the directory for SUBSCRIBERS_FILE exists; for "subscribers.json" it's the current dir.
#     # If SUBSCRIBERS_FILE included a path, e.g., "data/subscribers.json",
#     # os.makedirs(os.path.dirname(SUBSCRIBERS_FILE), exist_ok=True) would be needed.
#     # For now, assuming SUBSCRIBERS_FILE is in the current directory.

#     temp_fd, temp_path = -1, "" # Initialize to safe values
#     try:
#         # mkstemp needs a directory that exists.
#         # If SUBSCRIBERS_FILE is just a filename, dir will be '' (current dir)
#         # If SUBSCRIBERS_FILE has a path, os.path.dirname will return it.
#         file_dir = os.path.dirname(SUBSCRIBERS_FILE)
#         if file_dir == "": # Current directory
#             file_dir = "." 
        
#         if not os.path.isdir(file_dir):
#             logger.error(f"Directory {file_dir} for subscribers file does not exist. Cannot save.")
#             return # Cannot proceed if directory doesn't exist

#         temp_fd, temp_path = tempfile.mkstemp(dir=file_dir, prefix=os.path.basename(SUBSCRIBERS_FILE) + ".tmp_")
#         with os.fdopen(temp_fd, "w") as f:
#             json.dump(list(subscribers_set), f)
#         temp_fd = -1 # fd is closed by os.fdopen context manager

#         # If write is successful, atomically replace the old file
#         os.replace(temp_path, SUBSCRIBERS_FILE)
#         logger.debug(f"Subscribers saved to {SUBSCRIBERS_FILE}")
#         temp_path = "" # Mark as successfully moved
#     except Exception as e:
#         logger.error(f"Error saving subscribers to {SUBSCRIBERS_FILE}: {e}", exc_info=True)
#     finally:
#         # Clean up temp file if it still exists (e.g., os.replace failed or error before it)
#         if temp_fd != -1: # If fdopen didn't take ownership or failed before
#             try:
#                 os.close(temp_fd)
#             except OSError as e_close:
#                 logger.error(f"Error closing temp_fd during cleanup: {e_close}")
#         if temp_path and os.path.exists(temp_path): # Check if temp_path is set and exists
#             try:
#                 os.remove(temp_path)
#                 logger.debug(f"Removed temporary subscriber file {temp_path} during cleanup.")
#             except Exception as re:
#                 logger.error(f"Error removing temporary subscriber file {temp_path} during cleanup: {re}")

# In bot.py

# REMOVE: import tempfile
# ... (other imports)

# ...

# In bot.py - use this for save_subscribers
def save_subscribers(subscribers_set):
    file_handle = None
    try:
        # Ensure the directory for SUBSCRIBERS_FILE exists.
        file_dir = os.path.dirname(SUBSCRIBERS_FILE)
        if file_dir and not os.path.exists(file_dir):
            try:
                os.makedirs(file_dir, exist_ok=True)
                logger.info(f"Created directory {file_dir} for subscribers file.")
            except Exception as e_mkdir:
                logger.error(f"Failed to create directory {file_dir}: {e_mkdir}. Cannot save subscribers.")
                return

        logger.debug(f"Attempting to open {SUBSCRIBERS_FILE} for writing.")
        file_handle = open(SUBSCRIBERS_FILE, "w")
        logger.debug(f"Successfully opened {SUBSCRIBERS_FILE}. Writing data.")
        json.dump(list(subscribers_set), file_handle)
        file_handle.flush() # Explicitly flush the buffer
        logger.info(f"Subscribers saved to {SUBSCRIBERS_FILE}")
    except OSError as e:
        logger.error(f"OSError saving subscribers to {SUBSCRIBERS_FILE}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Generic error saving subscribers to {SUBSCRIBERS_FILE}: {e}", exc_info=True)
    finally:
        if file_handle:
            try:
                file_handle.close()
                logger.debug(f"Closed file handle for {SUBSCRIBERS_FILE}.")
            except Exception as e_close:
                logger.error(f"Error closing file handle for {SUBSCRIBERS_FILE}: {e_close}")
# ... (rest of the bot.py code remains the same as the previous full version,
#      just make sure the `import tempfile` is removed/commented out
#      and `save_subscribers` is replaced with this simplified one)

subscribers = load_subscribers()
scheduler = BackgroundScheduler(timezone="UTC")

# --- Codeforces API ---
async def fetch_upcoming_contests():
    try:
        response = requests.get(CODEFORCES_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data["status"] == "OK":
            upcoming = [
                contest for contest in data["result"] if contest["phase"] == "BEFORE"
            ]
            upcoming.sort(key=lambda x: x["startTimeSeconds"])
            return upcoming
        else:
            logger.error(f"Codeforces API error: {data.get('comment', 'Unknown error')}")
            return []
    except requests.RequestException as e:
        logger.error(f"Error fetching contests from Codeforces: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error in fetch_upcoming_contests: {e}")
        return []

# --- Reminder Logic (Called by APScheduler) ---
async def send_actual_reminder(app: Application, contest: dict, interval_str: str):
    chat_ids_to_notify = list(subscribers)
    if not chat_ids_to_notify:
        logger.debug(f"No subscribers to notify for contest {contest['name']} ({interval_str} reminder)")
        return

    start_time_dt = datetime.fromtimestamp(contest["startTimeSeconds"], tz=timezone.utc)
    if start_time_dt <= datetime.now(timezone.utc) - timedelta(minutes=1):
        logger.info(f"Contest {contest['name']} has likely started or passed. Skipping {interval_str} reminder.")
        return

    message = (
        f"📢 Reminder: Codeforces Contest!\n\n"
        f"🔹 <b>{contest['name']}</b> 🔹\n"
        f"Starts in approximately: <b>{interval_str}</b>\n"
        f"Exact Start Time: {start_time_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"Duration: {timedelta(seconds=contest['durationSeconds'])}\n"
        f"🔗 Link: https://codeforces.com/contests/{contest['id']}\n\n"
        f"Good luck! ✨"
    )

    for chat_id in chat_ids_to_notify:
        try:
            await app.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
            logger.info(f"Sent {interval_str} reminder for {contest['name']} to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder to {chat_id} for {contest['name']}: {e}")
            error_str = str(e).lower()
            if "bot was blocked" in error_str or \
               "user is deactivated" in error_str or \
               "chat not found" in error_str or \
               "forbidden: bot was kicked" in error_str or \
               "forbidden: bot can't initiate conversation with a user" in error_str:
                logger.info(f"Removing {chat_id} from subscribers due to error: {e}")
                if chat_id in subscribers: # Check again before modifying
                    subscribers.discard(chat_id)
                    save_subscribers(subscribers) # Save immediately after removal

# --- Scheduling Logic ---
async def manage_and_schedule_reminders(app: Application):
    logger.info("Checking for new contests and (re)scheduling reminders...")
    contests = await fetch_upcoming_contests()
    now_utc = datetime.now(timezone.utc)

    if contests is None:
        logger.error("Failed to fetch contests, cannot schedule reminders.")
        return
    if not contests:
        logger.info("No upcoming contests found (or API error returned empty list).")
        return

    scheduled_count = 0
    for contest in contests:
        contest_id = contest["id"]
        contest_name = contest["name"]
        start_time_seconds = contest["startTimeSeconds"]
        start_time_dt = datetime.fromtimestamp(start_time_seconds, tz=timezone.utc)

        if start_time_dt <= now_utc:
            continue

        for interval_str, delta in REMINDER_INTERVALS.items():
            reminder_time_dt = start_time_dt - delta
            job_id = f"contest_{contest_id}_reminder_{interval_str}"

            if reminder_time_dt > now_utc:
                try:
                    # Check if job already exists or if its run_time needs update (less common here)
                    existing_job = scheduler.get_job(job_id)
                    if existing_job:
                        # If job exists and its time is significantly different, reschedule (optional)
                        # For simplicity, we assume if it exists, it's correct.
                        logger.debug(f"Reminder job {job_id} for {contest_name} already exists.")
                    else:
                        scheduler.add_job(
                            send_actual_reminder,
                            "date",
                            run_date=reminder_time_dt,
                            args=[app, contest, interval_str],
                            id=job_id,
                            misfire_grace_time=300 # 5 minutes
                        )
                        logger.info(f"Scheduled {interval_str} reminder for {contest_name} ({contest_id}) at {reminder_time_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        scheduled_count +=1
                except Exception as e:
                    logger.error(f"Error scheduling job {job_id} for {contest_name}: {e}", exc_info=True)
            else:
                logger.debug(f"{interval_str} reminder time for {contest_name} ({job_id}) has passed. Not scheduling.")
    
    if scheduled_count > 0:
        logger.info(f"Scheduled {scheduled_count} new reminder jobs in this run.")
    else:
        logger.info("No new reminder jobs were scheduled in this run (either already exist or times passed).")

# --- Telegram Command Handlers ---
async def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! I am your Codeforces Contest Reminder Bot. 🤖"
        "\n\nUse /subscribe to get upcoming contest reminders."
        "\nUse /unsubscribe to stop receiving reminders."
        "\nUse /upcoming to see the next few contests."
        "\nUse /help to see this message again."
        f"\n\nI will remind you {', '.join(REMINDER_INTERVALS.keys())} before each contest."
    )

async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Welcome message\n"
        "/subscribe - Get contest reminders\n"
        "/unsubscribe - Stop contest reminders\n"
        "/upcoming - Show upcoming Codeforces contests\n"
        "/help - Show this help message"
    )

async def subscribe_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id not in subscribers:
        subscribers.add(chat_id)
        save_subscribers(subscribers) # This will use the new robust save
        await update.message.reply_text("You are now subscribed to Codeforces contest reminders! 🎉")
        logger.info(f"Chat {chat_id} subscribed.")
        await manage_and_schedule_reminders(context.application)
    else:
        await update.message.reply_text("You are already subscribed. 👍")

async def unsubscribe_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        subscribers.discard(chat_id)
        save_subscribers(subscribers) # This will use the new robust save
        await update.message.reply_text("You have unsubscribed from reminders. You can /subscribe again anytime.")
        logger.info(f"Chat {chat_id} unsubscribed.")
    else:
        await update.message.reply_text("You were not subscribed.")

async def upcoming_command(update: Update, context: CallbackContext):
    await update.message.chat.send_action(action="typing")
    contests = await fetch_upcoming_contests()
    if contests is None or not contests:
        await update.message.reply_text("No upcoming contests found or Codeforces API is currently unavailable.")
        return

    message = "🗓️ Upcoming Codeforces Contests (max 5 shown):\n\n"
    count = 0
    for contest in contests[:5]:
        start_time = datetime.fromtimestamp(contest["startTimeSeconds"], tz=timezone.utc)
        message += (
            f"🔹 <b>{contest['name']}</b>\n"
            f"   📅 Starts: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"   ⏳ Duration: {timedelta(seconds=contest['durationSeconds'])}\n"
            f"   🔗 Link: https://codeforces.com/contests/{contest['id']}\n\n"
        )
        count +=1
    
    if count == 0:
        message = "No upcoming contests found at the moment."
    await update.message.reply_html(message)

async def unknown_command_handler(update: Update, context: CallbackContext):
    # Ignore edited messages that might re-trigger command handlers
    if update.edited_message:
        return
    await update.message.reply_text("Sorry, I didn't understand that command. Try /help")

# --- PTB Post Init Hook ---
async def post_initialization_hook(app: Application):
    commands = [
        BotCommand("start", "Welcome message and basic info"),
        BotCommand("subscribe", "Subscribe to contest reminders"),
        BotCommand("unsubscribe", "Unsubscribe from reminders"),
        BotCommand("upcoming", "Show upcoming contests"),
        BotCommand("help", "Show help message"),
    ]
    try:
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully via post_initialization_hook.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

    await manage_and_schedule_reminders(app)
    logger.info("Initial contest check and reminder scheduling triggered via post_initialization_hook.")

# --- Main Bot Setup ---

def main():
    print("Token: ", TELEGRAM_BOT_TOKEN)
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.critical("FATAL: TELEGRAM_BOT_TOKEN not set in config.py. Please set it and restart.")
        return

    # Create an application instance
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_initialization_hook)
        .build()
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    application.add_handler(CommandHandler("upcoming", upcoming_command))
    application.add_handler(MessageHandler(filters.COMMAND & (~filters.UpdateType.EDITED_MESSAGE), unknown_command_handler))

    # --- Scheduler Setup ---
    scheduler.add_job(
        manage_and_schedule_reminders,
        "interval",
        hours=SCHEDULER_CHECK_INTERVAL_HOURS,
        args=[application],
        id="periodic_contest_check",
        name="Periodic Codeforces Contest Check",
        replace_existing=True # If a job with this ID exists, replace it (good for restarts)
    )
    
    try:
        if not scheduler.running:
            scheduler.start(paused=False) # Ensure it's not started in paused state
            logger.info("APScheduler started. Bot is now polling for commands and contests.")
        else:
            logger.info("APScheduler already running.")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.critical(f"Critical error in main polling loop: {e}", exc_info=True)
    finally:
        logger.info("Bot shutting down...")
        if scheduler.running:
            try:
                # Give jobs a chance to finish, then force shutdown
                scheduler.shutdown(wait=False) # Don't wait indefinitely for jobs
                logger.info("APScheduler shut down initiated.")
            except Exception as e:
                logger.error(f"Error during APScheduler shutdown: {e}")
        else:
            logger.info("APScheduler was not running or already shut down.")
        logger.info("Bot shutdown complete.")

if __name__ == "__main__":
    # Before running, ensure the directory for SUBSCRIBERS_FILE exists if it's not the current dir.
    # For "subscribers.json", current directory is fine.
    # If SUBSCRIBERS_FILE = "data/subscribers.json", you might do:
    # script_dir = os.path.dirname(os.path.abspath(__file__))
    # data_dir = os.path.join(script_dir, "data")
    # os.makedirs(data_dir, exist_ok=True)
    logger.info(f"Current Working Directory: {os.getcwd()}") # Add this line
    logger.info(f"Absolute path for SUBSCRIBERS_FILE: {os.path.abspath(SUBSCRIBERS_FILE)}") # Add 
    main()