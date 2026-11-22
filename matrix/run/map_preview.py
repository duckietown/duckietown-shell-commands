"""Read the static tile layout without constructing an Engine map."""

from __future__ import annotations

import os
from math import cos, isfinite, remainder, sin, tau
from pathlib import Path
from stat import S_ISREG

import yaml


MAX_LAYER_BYTES = 512 * 1024
MAX_TILES = 1024
TILE_KINDS = ("straight", "curve", "3way", "4way", "asphalt", "floor")
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _fields(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("The map preview requires valid tile and frame layers.")
    return value


def _layer(directory: Path, name: str, *, optional: bool = False) -> dict:
    # The Engine reads named layer files directly. Do not follow includes or symlinks.
    path = directory / f"{name}.yaml"
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            if optional:
                return {}
            raise
        if not S_ISREG(info.st_mode):
            raise ValueError("The map preview requires regular YAML layer files.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            if not S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("The map preview requires regular YAML layer files.")
            content = source.read(MAX_LAYER_BYTES + 1)
    except OSError as error:
        raise ValueError("Could not read the selected map's layers for preview.") from error
    if len(content) > MAX_LAYER_BYTES:
        raise ValueError("The selected map's layers are too large to preview.")
    try:
        document = yaml.load(content, Loader=SAFE_LOADER)
    except (yaml.YAMLError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("Could not read the selected map's YAML for preview.") from error
    root = _fields(document)
    if name not in root:
        raise ValueError("The map preview requires valid tile and frame layers.")
    return {} if root[name] is None else _fields(root[name])


def _number(value: object) -> float:
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            pass
        else:
            if isfinite(number):
                return number
    raise ValueError("The map preview requires finite tile sizes and frame poses.")


def read_map_preview(directory: Path) -> list[dict]:
    """Return supported tiles in map coordinates, with yaw in radians."""
    tiles = _layer(directory, "tiles", optional=True)
    if not tiles:
        return []
    if len(tiles) > MAX_TILES:
        raise ValueError("The selected map has too many tiles to preview.")
    frames = _layer(directory, "frames")
    tile_maps = _layer(directory, "tile_maps")

    def tile_size(parent: str) -> tuple[float, float]:
        size = _fields(_fields(tile_maps.get(parent)).get("tile_size"))
        width, height = (_number(size.get(axis)) for axis in ("x", "y"))
        if width <= 0 or height <= 0:
            raise ValueError("The map preview requires positive tile sizes.")
        return width, height

    poses = {"": (0.0, 0.0, 0.0)}
    visiting = set()

    def world_pose(key: str) -> tuple[float, float, float]:
        if key in poses:
            return poses[key]
        if key in visiting or len(visiting) >= 64:
            raise ValueError("Could not resolve the selected map's frame hierarchy for preview.")
        visiting.add(key)
        frame = _fields(frames.get(key, {}))
        parent = key.rpartition("/")[0]
        relative = frame.get("relative_to")
        if relative is None:
            relative = parent
        if not isinstance(relative, str):
            raise ValueError("Could not resolve the selected map's frame hierarchy for preview.")
        pose = _fields(frame.get("pose", {}))
        if any(abs(_number(pose.get(axis, 0))) > 1e-6 for axis in ("roll", "pitch")):
            raise ValueError("The map preview supports planar tile layouts only.")
        x, y, yaw = (_number(pose.get(axis, 0)) for axis in ("x", "y", "yaw"))
        unit = frame.get("unit")
        if unit == "tiles":
            width, height = tile_size(parent)
            x, y = (x + 0.5) * width, (y + 0.5) * height
        elif unit not in (None, "meters"):
            raise ValueError("The map preview supports frames measured in tiles or meters.")
        px, py, angle = world_pose(relative)
        x, y = (px + cos(angle) * x - sin(angle) * y, py + sin(angle) * x + cos(angle) * y)
        result = (_number(x), _number(y), remainder(angle + remainder(yaw, tau), tau))
        poses[key] = result
        visiting.remove(key)
        return result

    preview = []
    for key, tile in tiles.items():
        kind = _fields(tile).get("type")
        if kind not in TILE_KINDS:
            continue
        if not isinstance(key, str) or "/" not in key:
            raise ValueError("Map preview tiles must belong to a tile map.")
        width, height = tile_size(key.rpartition("/")[0])
        x, y, yaw = world_pose(key)
        preview.append({"kind": kind, "x": x, "y": y, "width": width, "height": height, "yaw": yaw})
    return preview
