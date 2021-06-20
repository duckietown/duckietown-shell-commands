import os
import yaml

__all__ = ["load_yaml"]


def load_yaml(file_name: str):
    if not os.path.isfile(file_name):
        msg = f"File does not exist {file_name}"
        raise Exception(msg)
    with open(file_name) as f:
        try:
            env = yaml.load(f, Loader=yaml.FullLoader)
        except Exception as e:
            msg = f"Cannot load yaml file {file_name}"
            raise Exception(msg) from e
        else:
            return env
