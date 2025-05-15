MovieBot Telegram Bot

A Telegram bot that manages a custom calendar for movie or event scheduling. Users can add, list, and remove calendar entries through simple Telegram commands.
Features

    Add calendar entries with names and dates

    List all scheduled entries

    Remove entries from the calendar

    Persistent storage of calendar data

Commands

    /month <month>
    List all entries for the specified month.
    Example: /month July

    /remove <name>
    Remove an entry by name from the calendar.
    Example: /remove Mark

    /list or / list
    List all calendar entries.

    To add an entry, send a message in the following format (without a command prefix):
    <Name> <day> <month> <year>
    Example: Mark 19 July 2025

Installation

    Clone the repository:

git clone https://github.com/yourusername/moviebot.git
cd moviebot

Create and activate a Python virtual environment:

python3 -m venv venv
source venv/bin/activate  # bash/zsh  
# or for fish shell:  
. venv/bin/activate.fish

Install dependencies:

pip install -r requirements.txt

Set your Telegram bot token in the environment or a config file as required by the bot.

Run the bot:

    python main.py

Running as a Service

To run the bot as a systemd service and ensure it always restarts:

    Create a moviebot.service file in /etc/systemd/system/ with the correct path to your bot and virtual environment Python.

    Enable and start the service:

sudo systemctl enable moviebot.service
sudo systemctl start moviebot.service

Check logs:

    sudo journalctl -u moviebot.service -f

Notes

    Use the proper format when adding entries to avoid errors: <Name> <day> <month> <year>.

    For Fish shell users, activate the virtual environment with:

. venv/bin/activate.fish
