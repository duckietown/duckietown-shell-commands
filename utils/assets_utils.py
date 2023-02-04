import json
import os
import pathlib
from typing import Optional

ASSETS_DIR: str = os.path.join(pathlib.Path(__file__).parent.parent.absolute(), "assets")


def load_schema(name: str, version: str) -> dict:
    fpath: str = os.path.join(ASSETS_DIR, "schemas", name, version, "schema.json")
    if not os.path.exists(fpath):
        raise FileNotFoundError(fpath)
    with open(fpath, "rt") as fin:
        return json.load(fin)


def get_schema_icon_filepath(name: str, version: str) -> Optional[str]:
    fpath: str = os.path.join(ASSETS_DIR, "schemas", name, version, "icon.png")
    return fpath if os.path.exists(fpath) else None


def get_schema_html_filepath(name: str, version: str, component: str) -> Optional[str]:
    fpath: str = os.path.join(ASSETS_DIR, "schemas", name, version, component)
    return fpath if os.path.exists(fpath) else None


__all__ = [
    "ASSETS_DIR",
    "load_schema",
    "get_schema_icon_filepath",
    "get_schema_html_filepath"
]
