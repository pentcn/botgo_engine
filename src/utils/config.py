import os
from dotenv import load_dotenv


def load_pocketbase_config():
    load_dotenv()
    return {
        "SUPERUSER_EMAIL": os.getenv("SUPERUSER_EMAIL"),
        "SUPERUSER_PASSWORD": os.getenv("SUPERUSER_PASSWORD"),
        "POCKETBASE_URL": os.getenv("POCKETBASE_URL"),
    }


def load_history_db_config():
    load_dotenv()
    return {
        "DB_HOST": os.getenv("HISTORY_DOLPHIN_HOST"),
        "DB_PORT": int(os.getenv("HISTORY_DOLPHIN_PORT")),
        "DB_USER": os.getenv("HISTORY_DOLPHIN_USER"),
        "DB_PASSWORD": os.getenv("HISTORY_DOLPHIN_PASSWORD"),
        "DB_NAME": os.getenv("HISTORY_DATABASE_NAME"),
        "BAR_TABLE": os.getenv("HISTROY_BARTABLE_NAME"),
    }


def load_market_db_config():
    load_dotenv()
    return {
        "DB_HOST": os.getenv("MARKET_DOLPHIN_HOST"),
        "DB_PORT": int(os.getenv("MARKET_DOLPHIN_PORT")),
        "DB_USER": os.getenv("MARKET_DOLPHIN_USER"),
        "DB_PASSWORD": os.getenv("MARKET_DOLPHIN_PASSWORD"),
        "DB_NAME": os.getenv("MARKET_DATABASE_NAME"),
        "OPTION_CONTRACT_TABLE": os.getenv("MARKET_INSTRUMENTTABLE_NAME"),
        "STREAM_BAR_TABLE": os.getenv("MARKET_STREAM_BAR_NAME"),
        "TICK_TABLE": os.getenv("MARKET_STREAM_TICK_NAME"),
    }
