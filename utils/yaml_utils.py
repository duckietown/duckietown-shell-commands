from typing import Union

import os
import yaml

__all__ = ["load_yaml"]


def load_yaml(file_name: str) -> Union[dict, list, bytes, float, int, None]:
    if not os.path.isfile(file_name):
        msg = f"File does not exist {file_name}"
        raise Exception(msg)
    with open(file_name) as f:
        try:
            return yaml.safe_load(f) or {}
        except Exception as e:
            msg = f"Cannot load yaml file {file_name}"
            raise Exception(msg) from e
