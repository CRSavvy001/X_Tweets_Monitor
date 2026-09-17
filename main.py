"""Telegram bot that watches X (Twitter) handles via twitterapi.io and
forwards new tweets into the chat that requested the watch.

Commands:
  /watch <https://x.com/handle>   start watching (baseline only, no old-tweet flood)
  /unwatch <https://x.com/handle> stop watching
  /watching                       list handles watched in this chat
"""

import asyncio
import html
import logging
import os
import re
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from db import Database
from twitter_client import TwitterAPIClient, TwitterAPIError

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("tweet-watch-bot")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TWITTERAPI_IO_KEY = os.environ["TWITTERAPI_IO_KEY"]
DB_PATH = os.environ.get("DB_PATH", "watchlist.db")
# Gap between individual twitterapi.io calls, tuned for the free tier.
POLL_GAP_SECONDS = float(os.environ.get("POLL_GAP_SECONDS", "5.5"))

HANDLE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/(@?[A-Za-z0-9_]{1,15})"
)


def extract_handle(text: str) -> Optional[str]:
    """Pull a bare handle out of an x.com/twitter.com URL, or accept @handle."""
    text = text.strip()
    m = HANDLE_URL_RE.search(text)
    if m:
        return m.group(1).lstrip("@").lower()
    m2 = re.fullmatch(r"@?([A-Za-z0-9_]{1,15})", text)
    if m2:
        return m2.group(1).lower()
    return None


def format_tweet_message(tweet: dict) -> str:
    author = tweet.get("author") or {}
    name = html.escape(author.get("name") or author.get("userName") or "Unknown")
    username = author.get("userName") or "unknown"
    text = html.escape(tweet.get("text") or "")
    url = tweet.get("url") or f"https://x.com/{username}/status/{tweet.get('id')}"
    return f'🐦 <b>{name}</b> (@{username})\n\n{text}\n\n<a href="{url}">Open on X</a>'


class BotApp:
    def __init__(self):
        self.db = Database(DB_PATH)
        self.twitter = TwitterAPIClient(TWITTERAPI_IO_KEY)

    # -- commands ------------------------------------------------------

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Hi! I watch X (Twitter) accounts and forward new tweets into this chat.\n\n"
            "Commands:\n"
            "/watch <https://x.com/handle> — start watching an account\n"
            "/unwatch <https://x.com/handle> — stop watching an account\n"
            "/watching — list accounts watched in this chat"
        )

    async def cmd_watch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /watch https://x.com/handle")
            return
        handle = extract_handle(context.args[0])
        if not handle:
            await update.message.reply_text(
                "I couldn't find a handle in that. Try: /watch https://x.com/handle"
            )
            return

        chat_id = update.effective_chat.id

        if self.db.is_watching(chat_id, handle):
            await update.message.reply_text(f"Already watching @{handle} in this chat.")
            return

        # Only hit the API for a baseline if nobody is tracking this handle yet.
        state = self.db.get_handle_state(handle)
        if state is None:
            status_msg = await update.message.reply_text(
                f"Fetching @{handle}'s latest tweet as a baseline…"
            )
            try:
                tweets = await self.twitter.get_last_tweets(handle)
            except TwitterAPIError as e:
                await status_msg.edit_text(f"Couldn't fetch @{handle}: {e}")
                return
            baseline_id = tweets[0]["id"] if tweets else None
            logger.info("Baseline for @%s set to tweet id=%s", handle, baseline_id)
            self.db.set_handle_state(handle, baseline_id)

        self.db.add_watch(chat_id, handle)
        await update.message.reply_text(
            f"✅ Now watching @{handle}. Only new tweets posted from now on will be sent here."
        )

    async def cmd_unwatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /unwatch https://x.com/handle")
            return
        handle = extract_handle(context.args[0])
        if not handle:
            await update.message.reply_text("I couldn't find a handle in that.")
            return

        chat_id = update.effective_chat.id
        removed = self.db.remove_watch(chat_id, handle)
        if removed:
            await update.message.reply_text(f"🛑 Stopped watching @{handle} in this chat.")
        else:
            await update.message.reply_text(f"You weren't watching @{handle} in this chat.")

    async def cmd_watching(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        handles = self.db.list_watches(chat_id)
        if not handles:
            await update.message.reply_text("You're not watching any accounts in this chat yet.")
            return
        lines = "\n".join(f"• @{h}" for h in handles)
        await update.message.reply_text(f"Watching in this chat:\n{lines}")

    # -- polling ---------------------------------------------------------

    async def poll_loop(self, application: Application):
        logger.info("Starting poll loop (gap=%.1fs between checks)", POLL_GAP_SECONDS)
        while True:
            handles = self.db.list_active_handles()
            if not handles:
                await asyncio.sleep(POLL_GAP_SECONDS)
                continue
            for handle in handles:
                try:
                    await self.check_handle(application, handle)
                except Exception:
                    logger.exception("Error checking @%s", handle)
                await asyncio.sleep(POLL_GAP_SECONDS)

    async def check_handle(self, application: Application, handle: str):
        state = self.db.get_handle_state(handle)
        last_id = state["last_tweet_id"] if state else None

        try:
            tweets = await self.twitter.get_last_tweets(handle)
        except TwitterAPIError as e:
            logger.warning("Fetch failed for @%s: %s", handle, e)
            return

        # --- DIAGNOSTIC LOGGING (temporary) ---
        newest_id = tweets[0].get("id") if tweets else None
        logger.info(
            "Checked @%s: fetched %d tweet(s), stored last_id=%s, newest returned id=%s",
            handle, len(tweets), last_id, newest_id,
        )
        # ---------------------------------------

        if not tweets:
            return

        if last_id is None:
            self.db.set_handle_state(handle, tweets[0]["id"])
            return

        new_tweets = []
        for t in tweets:
            if t.get("id") == last_id:
                break
            new_tweets.append(t)

        logger.info("@%s: %d new tweet(s) to send", handle, len(new_tweets))

        if not new_tweets:
            return

        new_tweets.reverse()  # oldest first, so chat order matches posting order

        chat_ids = self.db.list_chats_for_handle(handle)
        for tweet in new_tweets:
            message = format_tweet_message(tweet)
            for chat_id in chat_ids:
                try:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    logger.exception("Failed to send tweet to chat %s", chat_id)

        self.db.set_handle_state(handle, tweets[0]["id"])


async def post_init(application: Application):
    app: BotApp = application.bot_data["app"]
    application.create_task(app.poll_loop(application))


def main():
    bot_app = BotApp()
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.bot_data["app"] = bot_app

    application.add_handler(CommandHandler("start", bot_app.cmd_start))
    application.add_handler(CommandHandler("watch", bot_app.cmd_watch))
    application.add_handler(CommandHandler("unwatch", bot_app.cmd_unwatch))
    application.add_handler(CommandHandler("watching", bot_app.cmd_watching))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
