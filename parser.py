import asyncio
import logging

from telethon.errors import RPCError
from telethon.sync import TelegramClient
from telethon.tl.custom.message import Message

from db import save_post

logger = logging.getLogger(__name__)


def _ensure_loop():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def create_client(session_name, api_id, api_hash):
    _ensure_loop()
    client = TelegramClient(session_name, api_id, api_hash)
    client.start()
    return client


def _message_date(message):
    if message.date is None:
        return None
    return message.date.replace(tzinfo=None)


def fetch_channel_posts(client, channel, limit=100):
    saved = 0
    try:
        messages = client.iter_messages(channel, limit=limit)
        for message in messages:
            if not isinstance(message, Message):
                continue
            channel_id = message.peer_id.channel_id if message.peer_id else channel
            channel_title = message.chat.title if message.chat else None
            if message.id is None:
                continue
            save_post(
                str(channel_id),
                message.id,
                message.message,
                _message_date(message),
                channel_title,
            )
            saved += 1
    except RPCError as error:
        logger.error("Telethon error for %s: %s", channel, error)
    except ValueError as error:
        logger.error("Date error for %s: %s", channel, error)
    return saved


def fetch_channels(client, channels, limit_per_channel=100):
    total = 0
    for channel in channels:
        count = fetch_channel_posts(client, channel, limit_per_channel)
        logger.info("%s -> %s posts", channel, count)
        total += count
    return total


def close_client(client):
    client.disconnect()
