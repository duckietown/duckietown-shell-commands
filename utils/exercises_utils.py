BASELINE_IMAGES = {
    "template_ros": "duckietown/challenge-aido_lf-template-ros:ente",
    "duckietown_baseline": "duckietown/challenge-aido_lf-baseline-duckietown:ente",
    "template_random": "duckietown/challenge-aido_lf-template-random:ente",
    "duckietown_ml": "duckietown/challenge-aido_lf-baseline-duckietown-ml:ente"
}

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dt_shell import dtslogger, UserError

from .yaml_utils import load_yaml


@dataclass
class ExerciseConfig:
    exercise_name: str
    root: str

    files: dict
    ws_dir: Optional[str]
    lab_dir: Optional[str]


def get_exercise_config(d=None) -> ExerciseConfig:
    if d is None:
        working_dir = os.getcwd()
    else:
        working_dir = d

    exercise_name = Path(working_dir).stem
    dtslogger.info(f"Exercise name: {exercise_name}")
    # make sure we are in an exercise directory
    cfile_name = "config.yaml"
    cfile = os.path.join(working_dir, cfile_name)
    if not os.path.exists(cfile):
        msg = f"You must run this command inside an exercise directory " f"containing a `{cfile_name}` file."
        raise UserError(msg)
    config = load_yaml(cfile)

    c = ExerciseConfig(
        files=config.get("files", []),
        ws_dir=config.get("ws_dir", None),
        lab_dir=config.get("lab_dir", None),
        exercise_name=exercise_name,
        root=working_dir,
    )
    return c
