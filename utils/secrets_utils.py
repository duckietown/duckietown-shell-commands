import os.path

import atexit
import base64
import json
import tempfile
import yaml
from pathlib import Path
from typing import Any, Union

from dt_shell import dtslogger
from utils.exceptions import SecretNotFound
from utils.misc_utils import NotSet

DEFAULT_SECRETS_DIR = os.path.expanduser("~/.duckietown/secrets")
SECRETS_DIR = os.environ.get("DT_SECRETS_DIR", DEFAULT_SECRETS_DIR)

if SECRETS_DIR != DEFAULT_SECRETS_DIR:
    dtslogger.info(f"Using secrets from '{SECRETS_DIR}' as instructed by the variable DT_SECRETS_DIR")
else:
    os.makedirs(SECRETS_DIR, exist_ok=True)

FilePath = str


class SecretsManager:

    @classmethod
    def get(cls, key: str, default: "Secret" = NotSet) -> "Secret":
        path: FilePath = cls._secret_filepath(key)
        if not os.path.isfile(path):
            if default is NotSet:
                raise SecretNotFound(f"No secrets with key '{key}' were found.")
            return default
        with open(path, "rb") as fin:
            raw: bytes = fin.read()
        # deserialize secret
        encoded: str = base64.b64decode(raw).decode("utf-8")
        parsed: Any = yaml.safe_load(encoded)
        return Secret(parsed)

    @classmethod
    def set(cls, key: str, value: Union[str, int, dict]):
        path: FilePath = cls._secret_filepath(key)
        # make sure the directory exists
        os.makedirs(Path(path).parent, exist_ok=True)
        # serialize secret
        parsed: str = yaml.safe_dump(value)
        encoded: bytes = base64.b64encode(parsed.encode("utf-8"))
        with open(path, "wb") as fout:
            fout.write(encoded)
        os.chmod(path, 0o600)

    @classmethod
    def has(cls, key: str) -> bool:
        path: FilePath = cls._secret_filepath(key)
        return os.path.isfile(path)

    @staticmethod
    def _secret_filepath(key: str, ext: str = "b6s") -> FilePath:
        keepcharacters = ('.', '-', '_', '/')
        key = key.lower()
        key = key.rstrip().rstrip(".")
        key = "".join(c for c in key if c.isalnum() or c in keepcharacters) + f".{ext}"
        return os.path.join(SECRETS_DIR, key)


class Secret:

    def __init__(self, value: Union[str, int, dict]):
        self._value = value

    def __getitem__(self, item):
        if not isinstance(self._value, dict):
            raise ValueError(f"Secret of type '{type(self._value)}' cannot be indexed.")
        return self._value[item]

    @property
    def as_text(self) -> str:
        if isinstance(self._value, dict):
            return self.as_json
        return str(self._value)

    @property
    def as_json(self) -> str:
        return json.dumps(self._value)

    @classmethod
    def _temporary_file(cls, content: str, autoremove: bool = True) -> FilePath:
        # create temporary file and write content to it
        tmpf_fd, tmpf_fpath = tempfile.mkstemp()
        os.write(tmpf_fd, content.encode("utf-8"))
        os.close(tmpf_fd)
        # when Python exits, the file gets removed
        if autoremove:
            atexit.register(os.remove, tmpf_fpath)
        # ---
        return tmpf_fpath

    @property
    def temporary_text_file(self) -> FilePath:
        return self._temporary_file(self.as_text)

    @property
    def temporary_json_file(self) -> FilePath:
        return self._temporary_file(self.as_json)

    @property
    def text_file(self) -> FilePath:
        return self._temporary_file(self.as_text, autoremove=False)

    @property
    def json_file(self) -> FilePath:
        return self._temporary_file(self.as_json, autoremove=False)
