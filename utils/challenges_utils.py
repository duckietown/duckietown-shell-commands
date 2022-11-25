import os

import requests

DEFAULT_CHALLENGES_SERVER: str = "https://challenges.duckietown.org/v4"


def get_challenges_server_to_use() -> str:
    return os.environ.get("DTSERVER", DEFAULT_CHALLENGES_SERVER)


def get_registry_from_challenges_server(server: str) -> str:
    url: str = f"{server}/api/registry-info"
    response: requests.Response = requests.get(url)
    data = response.json()
    return data["result"]["registry"]
