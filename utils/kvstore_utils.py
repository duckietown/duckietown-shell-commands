from functools import lru_cache
from typing import TypeVar, Type, Union, Any

import cbor2
import requests

from dt_shell import dtslogger
from duckietown_messages.base import BaseMessage
from utils.exceptions import NoTracebackException
from utils.networking_utils import best_host_for_robot

KVSTORE_URL = "http://{host}:{port}/{path}/"
KVSTORE_DEFAULT_PORT = 11411

T = TypeVar("T")
NOTSET = object()


class KVStoreUnreachable(NoTracebackException):
    pass


class KVStore:

    def __init__(self, robot: str, port: int = KVSTORE_DEFAULT_PORT):
        self._robot: str = robot
        host: str = best_host_for_robot(robot)
        self.url = KVSTORE_URL.format(host=host, port=port, path="{path}")

    def _url(self, path: str):
        return self.url.format(path=path.strip("/"))

    @lru_cache
    def is_available(self) -> bool:
        url = self._url("dtps")
        try:
            response = requests.get(url)
            return response.status_code == 200
        except requests.exceptions.ConnectionError:
            return False

    def has(self, key: str) -> bool:
        url = self._url(f"data/{key}")
        dtslogger.debug(f"KVStore[{self._robot}]: Probing key '{key}' for existence...")
        dtslogger.debug(f"$ HEAD {url}")
        try:
            response = requests.head(url)
        except requests.exceptions.ConnectionError:
            raise KVStoreUnreachable(f"KVStore at '{url}' is unreachable")
        dtslogger.debug(f" << {response.status_code}: {response.text}")
        return response.status_code == 200

    def get(self, cls: Type[T], key: str, default: Any = NOTSET) -> T:
        if not self.has(key):
            if default is NOTSET:
                msg = f"Key '{key}' not found"
                raise KeyError(msg)
            return default
        # fetch the value
        url = self._url(f"data/{key}")
        dtslogger.debug(f"KVStore[{self._robot}]: Fetching value for key '{key}'...")
        dtslogger.debug(f"$ GET {url}")
        response = requests.get(url)
        dtslogger.debug(f" << {response.status_code}: {response.text}")
        # decode the response
        native: Union[dict, list, str, int, float, bool, bytes] = cbor2.loads(response.content)
        if not isinstance(native, cls):
            msg = f"Expected value of type '{cls}' but got '{native.__class__.__name__}' instead"
            raise ValueError(msg)
        return native

    def set(self, key: str, value: Union[BaseMessage, dict, list, str, int, float, bool, bytes], persist: bool = False,
            fail_quietly: bool = False):
        # base messages can be turned into dicts
        if isinstance(value, BaseMessage):
            value = value.dict()
        # ---
        if self.has(key):
            # update existing field
            url = self._url(f"data/{key}")
            dtslogger.debug(f"KVStore[{self._robot}]: Updating key '{key}' to value '{value}'")
            dtslogger.debug(f"$ POST {url}\n"
                            f"--- request body ---\n"
                            f"{value}\n"
                            f"--------------------")
            response = requests.post(url, json=value)
            dtslogger.debug(f"$ POST {url}\n"
                            f"--- response [{response.status_code}] ---  (url: {url})\n"
                            f"{response.text}\n"
                            f"----------------------")
            if not fail_quietly:
                response.raise_for_status()
        else:
            # define new field
            url = self._url("define")
            data = {"key": key, "value": value, "persist": persist}
            adj = "persistent" if persist else "volatile"
            dtslogger.debug(f"KVStore[{self._robot}]: Defining new {adj} key '{key}' with initial value '{value}'")
            dtslogger.debug(f"$ POST {url}\n\t{data}")
            response = requests.post(url, json=data)
            dtslogger.debug(f" << {response.status_code}: {response.text}")
            if not fail_quietly:
                response.raise_for_status()
