import html
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import CallbackContext, CommandHandler, Filters, MessageHandler, Updater

from config import (
    SEARCH_RESULT_LIMIT,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNELS,
    TELEGRAM_FETCH_LIMIT,
    TELEGRAM_SESSION_NAME,
)
from db import (
    advanced_search_posts,
    get_channels,
    get_db_stats,
    get_latest_posts,
    init_db,
    search_posts,
)
from parser import close_client, create_client, fetch_channels

logger = logging.getLogger(__name__)

BUTTON_UPDATE = "🔄 Обновить базу"
BUTTON_LATEST = "📰 Свежие новости"
BUTTON_HELP = "ℹ️ Помощь"
BUTTON_RECENT = "⏱️ Последние"
BUTTON_CHANNELS = "📚 Каналы"
BUTTON_STATS = "📊 Статистика"

news_buffer = []


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _format_date(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def _make_snippet(text, words=None, limit=160):
    if not text:
        return "(пусто)"
    source = " ".join(str(text).split())
    if not words:
        if len(source) <= limit:
            return source
        return source[:limit] + "..."
    low = source.lower()
    pos = -1
    for w in words:
        w2 = str(w).strip().lower()
        if not w2:
            continue
        idx = low.find(w2)
        if idx != -1 and (pos == -1 or idx < pos):
            pos = idx
    if pos == -1:
        if len(source) <= limit:
            return source
        return source[:limit] + "..."
    left = max(0, pos - int(limit / 3))
    right = min(len(source), left + limit)
    part = source[left:right]
    if left > 0:
        part = "..." + part
    if right < len(source):
        part = part + "..."
    return part


def post_public_url(post):
    mid = post.get("message_id")
    if mid is None:
        return None
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return None
    un = post.get("channel_username")
    if un:
        u = str(un).strip().lstrip("@")
        if u:
            return f"https://t.me/{u}/{mid}"
    cid = post.get("channel_id")
    if cid is not None and str(cid).strip():
        cs = str(cid).strip()
        if cs.isdigit():
            return f"https://t.me/c/{cs}/{mid}"
    return None


def _post_url_keyboard(url):
    if not url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("Открыть в Telegram", url=url)]])


def post_card_html(post, idx=None, words=None):
    channel = post.get("channel_title") or post.get("channel_username") or post.get("channel_id") or "Канал"
    channel = html.escape(str(channel))
    dt_raw = _format_date(post.get("message_date")) or "?"
    dt = html.escape(dt_raw)
    mid = post.get("message_id")
    snippet_src = _make_snippet(post.get("message_text") or "", words=words, limit=500)
    snippet = html.escape(snippet_src)
    rel = post.get("relevance_score")
    parts = []
    if idx is not None:
        parts.append(f"<b>#{idx}</b> {channel}")
    else:
        parts.append(f"<b>{channel}</b>")
    parts.append(f"Дата: <code>{dt}</code>")
    if mid is not None:
        parts.append(f"id: <code>{html.escape(str(mid))}</code>")
    if rel is not None:
        parts.append(f"Релевантность: <code>{html.escape(str(rel))}</code>")
    parts.append("")
    parts.append(snippet)
    out = "\n".join(parts)
    if len(out) > 4000:
        out = out[:3997] + "..."
    return out


def send_posts_as_messages(update: Update, posts, words=None, header_html=None):
    msg = update.message
    if header_html:
        msg.reply_text(header_html, parse_mode="HTML")
    for i, post in enumerate(posts, 1):
        text = post_card_html(post, idx=i, words=words)
        url = post_public_url(post)
        km = _post_url_keyboard(url)
        msg.reply_text(text, parse_mode="HTML", reply_markup=km)


def _split_words(text):
    arr = []
    for p in str(text).replace(",", " ").split():
        p = p.strip()
        if p:
            arr.append(p)
    return arr


def parse_advanced_args(text):
    mode = "all"
    sort = "date"
    limit = 10
    channel = None
    raw_query = []
    parts = str(text or "").split()
    for p in parts:
        if "=" in p:
            key, value = p.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if k == "mode":
                mode = v.lower()
            elif k == "sort":
                sort = v.lower()
            elif k == "limit":
                try:
                    limit = int(v)
                except ValueError:
                    pass
            elif k == "channel":
                channel = v
            else:
                raw_query.append(p)
        else:
            raw_query.append(p)

    query = " ".join(raw_query).strip()
    words = _split_words(query)
    return {
        "mode": mode,
        "sort": sort,
        "limit": limit,
        "channel": channel,
        "query": query,
        "words": words,
    }


def build_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BUTTON_UPDATE, BUTTON_LATEST],
            [BUTTON_RECENT, BUTTON_CHANNELS],
            [BUTTON_STATS, BUTTON_HELP],
        ],
        resize_keyboard=True,
    )


def send_help(update: Update):
    help_text = (
        "<b>Привет!</b> Кнопки внизу или команды ниже.\n\n"
        "<b>Кнопки</b>\n"
        f"{html.escape(BUTTON_UPDATE)} — забрать новые посты\n"
        f"{html.escape(BUTTON_LATEST)} — показать свежие записи\n"
        f"{html.escape(BUTTON_RECENT)} — показать последние посты\n"
        f"{html.escape(BUTTON_CHANNELS)} — список каналов из базы\n"
        f"{html.escape(BUTTON_STATS)} — статистика по базе\n\n"
        "Просто текст в чат — обычный поиск по базе.\n\n"
        "<b>Команды</b>\n"
        "<code>/search iphone ai</code>\n"
        "<code>/advanced_search mode=all sort=relevance limit=7 channel=@tech ai новости</code>\n"
        "<code>/recent 5</code>\n"
        "<code>/channels</code>\n"
        "<code>/stats</code>"
    )
    update.message.reply_text(help_text, parse_mode="HTML", reply_markup=build_keyboard())


def start_command(update: Update, context: CallbackContext):
    send_help(update)


def help_command(update: Update, context: CallbackContext):
    send_help(update)


def _refresh_buffer(limit=SEARCH_RESULT_LIMIT):
    global news_buffer
    news_buffer = get_latest_posts(limit)


def send_latest(update: Update):
    if not news_buffer:
        _refresh_buffer()
    if not news_buffer:
        update.message.reply_text("Буфер пуст. Сначала обновите базу.")
        return
    send_posts_as_messages(update, news_buffer, words=None, header_html="<b>Свежие из буфера</b>")


def send_recent(update: Update, context: CallbackContext):
    lim = SEARCH_RESULT_LIMIT
    if context.args:
        try:
            lim = int(context.args[0])
        except ValueError:
            lim = SEARCH_RESULT_LIMIT
    if lim <= 0:
        lim = SEARCH_RESULT_LIMIT
    if lim > 30:
        lim = 30
    recent = get_latest_posts(limit=lim)
    if not recent:
        update.message.reply_text("Пока нет постов в базе.")
        return
    send_posts_as_messages(update, recent, words=None, header_html=f"<b>Последние посты</b> (до {lim})")


def show_channels(update: Update):
    channels = get_channels()
    if not channels:
        update.message.reply_text("Каналы в базе не найдены.")
        return
    lines = ["Каналы в базе:"]
    i = 1
    for ch in channels:
        title = ch.get("channel_title") or "-"
        cid = ch.get("channel_id") or "-"
        lines.append(f"{i}) {title} ({cid})")
        i += 1
    update.message.reply_text("\n".join(lines))


def show_stats(update: Update):
    stats = get_db_stats()
    total = stats.get("total_posts", 0)
    channels = stats.get("channels", [])
    per_channel = stats.get("posts_per_channel", [])
    last_date = _format_date(stats.get("last_post_date"))
    lines = []
    lines.append("Статистика базы")
    lines.append(f"Всего постов: {total}")
    lines.append(f"Количество каналов: {len(channels)}")
    lines.append(f"Последняя дата поста: {last_date or '-'}")
    lines.append("")
    lines.append("По каналам:")
    for row in per_channel[:20]:
        name = row.get("channel_title") or row.get("channel_id") or "?"
        count = row.get("posts_count", 0)
        lines.append(f"- {name}: {count}")
    if not per_channel:
        lines.append("- пусто")
    update.message.reply_text("\n".join(lines))


def search_command(update: Update, context: CallbackContext):
    query = " ".join(context.args).strip()
    if not query:
        update.message.reply_text("Использование: /search <запрос>")
        return
    results = search_posts(query, limit=SEARCH_RESULT_LIMIT)
    if not results:
        update.message.reply_text("Ничего не найдено.")
        return
    words = _split_words(query)
    send_posts_as_messages(update, results, words=words, header_html="<b>Поиск /search</b>")


def advanced_search_command(update: Update, context: CallbackContext):
    raw = " ".join(context.args).strip()
    if not raw:
        update.message.reply_text(
            "Использование: /advanced_search mode=all sort=date limit=10 channel=@name текст"
        )
        return
    parsed = parse_advanced_args(raw)
    words = parsed.get("words") or []
    if not words:
        update.message.reply_text("Не понял запрос. Нужны слова для поиска.")
        return
    result = advanced_search_posts(
        words,
        mode=parsed.get("mode", "all"),
        limit=parsed.get("limit", 10),
        sort=parsed.get("sort", "date"),
        channel_filter=parsed.get("channel"),
    )
    if not result:
        update.message.reply_text("Ничего не найдено по advanced_search.")
        return
    ch = parsed.get("channel") or "-"
    header = (
        "<b>Расширенный поиск</b>\n"
        f"mode: <code>{html.escape(str(parsed.get('mode')))}</code> · "
        f"sort: <code>{html.escape(str(parsed.get('sort')))}</code> · "
        f"limit: <code>{html.escape(str(parsed.get('limit')))}</code>\n"
        f"channel: <code>{html.escape(str(ch))}</code>"
    )
    send_posts_as_messages(update, result, words=words, header_html=header)


def perform_update(update: Update):
    if not TELEGRAM_CHANNELS:
        update.message.reply_text("Список каналов пуст. Заполните config.py.")
        return
    update.message.reply_text("Обновляю базу, подождите…")
    client = create_client(TELEGRAM_SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    try:
        saved = fetch_channels(client, TELEGRAM_CHANNELS, TELEGRAM_FETCH_LIMIT)
        _refresh_buffer()
        update.message.reply_text(f"Готово! Сохранено {saved} постов.")
    finally:
        close_client(client)


def update_command(update: Update, context: CallbackContext):
    perform_update(update)


def latest_command(update: Update, context: CallbackContext):
    send_latest(update)


def recent_command(update: Update, context: CallbackContext):
    send_recent(update, context)


def channels_command(update: Update, context: CallbackContext):
    show_channels(update)


def stats_command(update: Update, context: CallbackContext):
    show_stats(update)


def search_handler(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()
    if text in {BUTTON_UPDATE, "/update"}:
        perform_update(update)
        return
    if text in {BUTTON_LATEST, "/latest"}:
        send_latest(update)
        return
    if text in {BUTTON_HELP, "/help"}:
        send_help(update)
        return
    if text in {BUTTON_RECENT, "/recent"}:
        send_recent(update, context)
        return
    if text in {BUTTON_CHANNELS, "/channels"}:
        show_channels(update)
        return
    if text in {BUTTON_STATS, "/stats"}:
        show_stats(update)
        return
    if not text:
        update.message.reply_text("Введите запрос для поиска.")
        return
    results = search_posts(text, limit=SEARCH_RESULT_LIMIT)
    if not results:
        update.message.reply_text("Ничего не найдено.")
        return
    for post in reversed(results):
        news_buffer.insert(0, post)
    while len(news_buffer) > SEARCH_RESULT_LIMIT:
        news_buffer.pop()
    w = _split_words(text)
    send_posts_as_messages(update, results, words=w, header_html="<b>Поиск по тексту</b>")


def main():
    setup_logging()
    init_db()
    _refresh_buffer()
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("update", update_command))
    dispatcher.add_handler(CommandHandler("latest", latest_command))
    dispatcher.add_handler(CommandHandler("search", search_command))
    dispatcher.add_handler(CommandHandler("advanced_search", advanced_search_command))
    dispatcher.add_handler(CommandHandler("recent", recent_command))
    dispatcher.add_handler(CommandHandler("channels", channels_command))
    dispatcher.add_handler(CommandHandler("stats", stats_command))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, search_handler))
    logger.info("Бот запущен. Ожидаю сообщения…")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()


