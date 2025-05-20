import os
from dotenv import load_dotenv


def load_config():
    load_dotenv()
    return {
        "SUPERUSER_EMAIL": os.getenv("SUPERUSER_EMAIL"),
        "SUPERUSER_PASSWORD": os.getenv("SUPERUSER_PASSWORD"),
        "POCKETBASE_URL": os.getenv("POCKETBASE_URL"),
    }
