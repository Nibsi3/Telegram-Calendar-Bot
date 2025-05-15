from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import dateparser
from pathlib import Path
import os
import asyncio
import calendar
import matplotlib.pyplot as plt
from io import BytesIO


from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from datetime import datetime, timezone  # Correct imports
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}

now = datetime.now(timezone.utc).isoformat()

# Google Calendar API scope
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

EVENTS_FILE = Path("events.txt")

BOT_TOKEN = ""  # Replace with your actual token

def generate_calendar_image(month: int, year: int) -> BytesIO:
    cal = calendar.TextCalendar(calendar.SUNDAY)
    cal_str = cal.formatmonth(year, month)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.text(0.5, 0.5, cal_str, fontsize=12, fontfamily='monospace',
            verticalalignment='center', horizontalalignment='center')
    ax.axis('off')

    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    return buf

def create_event(title: str, date: datetime):
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)

    event = {
        'summary': title,
        'start': {
            'date': date.strftime('%Y-%m-%d'),
            'timeZone': 'Africa/Johannesburg',
        },
        'end': {
            'date': date.strftime('%Y-%m-%d'),
            'timeZone': 'Africa/Johannesburg',
        },
    }

    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return created_event.get("htmlLink")


def remove_event(title: str):
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)

    events_result = service.events().list(
    calendarId='primary',
    singleEvents=True,
    orderBy='startTime'
).execute()


    events = events_result.get('items', [])
    if not events:
        return None

    deleted_events = []
    for event in events:
        if title.strip().lower() in event.get('summary', '').strip().lower():
            service.events().delete(calendarId='primary', eventId=event['id']).execute()
            deleted_events.append(event['summary'])

    return deleted_events


def remove_event_from_file(title: str):
    if not EVENTS_FILE.exists():
        return False

    lines = EVENTS_FILE.read_text().splitlines()
    filtered_lines = [line for line in lines if title.strip().lower() not in line.lower()]

    if len(filtered_lines) == len(lines):
        return False  # Nothing removed

    EVENTS_FILE.write_text("\n".join(filtered_lines) + "\n")
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! 👋 I'm your movie & event bot.\n"
        "Send me something like:\n\n"
        "Stranger Things 01 July 2025"
    )

async def month_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.lower().lstrip('/')
    month_num = MONTHS.get(command)
    if not month_num:
        await update.message.reply_text("❌ Invalid month command.")
        return

    year = datetime.now().year
    image_buf = generate_calendar_image(month_num, year)
    await update.message.reply_photo(photo=image_buf, caption=f"{command.capitalize()} {year}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    words = user_message.split()

    if len(words) < 3:
        await update.message.reply_text("❌ Please send something like: Stranger Things 01 July 2025")
        return

    possible_date = " ".join(words[-3:])
    parsed_date = dateparser.parse(possible_date)

    if parsed_date:
        title = " ".join(words[:-3])
        date_str = parsed_date.strftime('%d %B %Y')

        with open(EVENTS_FILE, "a") as f:
            f.write(f"{title} - {date_str}\n")

        event_link = await asyncio.to_thread(create_event, title, parsed_date)

        await update.message.reply_text(
            f"✅ Got it!\n"
            f"Title: *{title}*\n"
            f"Date: *{date_str}*\n\n"
            f"🗓️ Event added to your Google Calendar:\n{event_link}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "❌ I couldn't understand the date. Please use a format like: 01 July 2025"
        )


async def remove_event_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Please provide the event title to remove. Usage:\n/remove Event Title"
        )
        return

    title = " ".join(args)
    deleted = await asyncio.to_thread(remove_event, title)
    if deleted:
        await update.message.reply_text(f"✅ Removed event(s) titled: *{title}*", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No event found with the title: *{title}*", parse_mode="Markdown")


async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if EVENTS_FILE.exists():
        lines = EVENTS_FILE.read_text().splitlines()
        unique_lines = list(dict.fromkeys(line.strip() for line in lines if line.strip()))
        if unique_lines:
            await update.message.reply_text(f"📅 *Your Events:*\n" + "\n".join(unique_lines), parse_mode="Markdown")
        else:
            await update.message.reply_text("📭 You don't have any events saved yet.")
    else:
        await update.message.reply_text("📭 No event list found yet.")


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_events))
    app.add_handler(CommandHandler("remove", remove_event_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

      # Month image calendar commands
    for month in MONTHS:
        app.add_handler(CommandHandler(month, month_command))

    print("🤖 Bot is running...")
    app.run_polling()
