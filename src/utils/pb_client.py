from pocketbase import PocketBase
from .config import load_config


def get_pb_client():
    config = load_config()
    client = PocketBase(config["POCKETBASE_URL"])
    client.admins.auth_with_password(
        config["SUPERUSER_EMAIL"], config["SUPERUSER_PASSWORD"]
    )
    return client
