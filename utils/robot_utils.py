import json
import time
from typing import Optional

import requests

from dt_shell import dtslogger
from utils.misc_utils import sanitize_hostname


def get_robot_type(robot: str, hostname: str) -> str:
    try:
        from utils.kvstore_utils import KVStore

        store = KVStore(hostname)
        if store.is_available():
            robot_type = store.get(str, "robot/type", None)
            if robot_type:
                return robot_type
    except Exception as error:
        dtslogger.debug(f"Could not get robot type from KVStore at '{hostname}': {error}")

    from utils.avahi_utils import wait_for_service

    _, _, data = wait_for_service("DT::ROBOT_TYPE", robot)
    return data["type"]


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
    stamp = int(stamp * (10**9))
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
    try:
        create_file_in_robot_data_dir(hostname, filepath, content)
    except requests.exceptions.ConnectionError:
        pass
