import dataclasses
import os
from types import SimpleNamespace
from typing import Dict, Any, cast, Iterable, List, Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from dtproject import DTProject
from utils.yaml_utils import load_yaml


class DTCommand(DTCommandAbs):
    help = "Runs a Duckietown LX agent against a physical or virtual robot"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = DTCommand.parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = DTCommand.parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # Make sure the project recipe is present
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
                dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                project.set_recipe_dir(recipe_dir)
            else:
                raise UserError("This project does not support recipes")
        else:
            if parsed.recipe_version:
                project.set_recipe_version(parsed.recipe_version)
                dtslogger.info(f"Using recipe version on branch '{parsed.recipe_version}'")
            project.ensure_recipe_exists()
            project.ensure_recipe_updated()

        # get the exercise recipe
        recipe: DTProject = project.recipe

        # settings file is in the recipe
        settings_file: str = os.path.join(recipe.path, "settings.yaml")
        if not os.path.exists(settings_file):
            msg = "Recipe must contain a 'settings.yaml' file"
            dtslogger.error(msg)
            exit(1)
        settings: SettingsFile = SettingsFile_from_yaml(settings_file)

        dtslogger.info(f"Settings:\n{settings}")

        dtslogger.info("Running Duckiematrix...")
        run_namespace: SimpleNamespace = SimpleNamespace(
            standalone=True,
            map=f"{recipe.path}/assets/duckiematrix/map/{settings.matrix['map']}",
            sandbox=False,
            force_vulkan=False,
            links=[],
            delta_t=None,
            version=None,
            force_opengl=False,
            engine_hostname=None,
            renderer_id=None,
            renderer_key=None,
            no_pull=False,
            verbose=False,
        )

        return shell.include.matrix.run.command(shell, [], parsed=run_namespace)




@dataclasses.dataclass
class SettingsFile:

    matrix: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # whether the project uses ROS
    # TODO: do we still need this?
    ros: Optional[bool] = True

    # files to exclude when rsync-ing
    # TODO: do we still need this?
    rsync_exclude: List[str] = dataclasses.field(default_factory=list)

    # editor configuration
    editor: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def __str__(self) -> str:
        fields: Iterable[dataclasses.Field] = dataclasses.fields(SettingsFile)
        return "\n\t" + "\n\t".join(f"{field.name}: {getattr(self, field.name)}" for field in fields) + "\n"


# noinspection PyPep8Naming
def SettingsFile_from_yaml(filename: str) -> SettingsFile:
    data = load_yaml(filename)
    if not isinstance(data, dict):
        msg = f"Expected that the settings file {filename!r} would be a dictionary, obtained {type(data)}."
        raise Exception(msg)

    data_dict = cast(Dict[str, object], data)
    known: Dict[str, object] = {
        "matrix": {},
    }

    params = {}
    for k, default in known.items():
        params[k] = data_dict.get(k, default)

    extra = {}
    for k, v in data_dict.items():
        if k not in known:
            extra[k] = v
    if extra:
        dtslogger.warn(f"Ignoring extra keys {list(extra)} in {filename!r}")

    settings = SettingsFile(**params)

    return settings
