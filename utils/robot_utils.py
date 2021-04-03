import json
import time
from typing import Optional

import requests

from utils.misc_utils import sanitize_hostname


def create_file_in_robot_data_dir(hostname: str, filepath: str, content: str):
    filepath = filepath.lstrip("/")
    filepath = filepath[5:] if filepath.startswith("data/") else filepath
    hostname = sanitize_hostname(hostname)
    url = f"http://{hostname}/files/data/{filepath}"
    requests.post(url, data=content)


def log_event_on_robot(hostname: str, type: str, data: Optional[dict] = None, stamp: Optional[float] = None):
    # sanitize 'stamp'
    if stamp is None:
        stamp = time.time()
    # events store timestamps in nanoseconds
    stamp = int(stamp * (10 ** 9))
    # sanitize 'data'
    if data is None:
        data = {}
    else:
        # make sure the given data can be serialized in JSON
        _ = json.dumps(data)
    # last check of everything
    assert isinstance(type, str)
    assert isinstance(data, dict)
    assert isinstance(stamp, int)
    # compile content
    content = json.dumps({"type": type, "stamp": stamp, "data": data})
    filepath = f"stats/events/{stamp}.json"
    create_file_in_robot_data_dir(hostname, filepath, content)
