import json
import os
import pathlib
from typing import List, Optional

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


def load_dtproject(name: str, version: str) -> List:
    fpath: str = os.path.join(ASSETS_DIR, "dtprojects", name, version, ".dtproject")
    if not os.path.exists(fpath):
        raise FileNotFoundError(fpath)
    with open(fpath, "rt") as metastream:
        lines: List[str] = metastream.readlines()
        return lines


def load_template(name: str, version: str) -> dict:
    fpath: str = os.path.join(ASSETS_DIR, "templates", name, version, "template.json")
    if not os.path.exists(fpath):
        raise FileNotFoundError(fpath)
    with open(fpath, "rt") as fin:
        return json.load(fin)


def get_asset_path(kind: str, name: str, version: str, *path) -> str:
    return os.path.join(ASSETS_DIR, kind, name, version, *path)


def get_asset_bin_path(name: str) -> str:
    return os.path.join(ASSETS_DIR, "bin", name)


__all__ = [
    "ASSETS_DIR",
    "load_schema",
    "get_schema_icon_filepath",
    "get_schema_html_filepath",
    "load_dtproject",
    "load_template",
    "get_asset_path",
    "get_asset_bin_path",
]
