import dataclasses
import os
from types import SimpleNamespace
from typing import Dict, Any, cast, Iterable, List, Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from dtproject import DTProject
from utils.yaml_utils import load_yaml
import multiprocessing


class DTCommand(DTCommandAbs):
    help = "Runs a Duckietown LX agent against a physical or virtual robot"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = DTCommand.parser.parse_args(args=args)
        else:
            parsed = DTCommand._resolve_parsed([], parsed)

        # -R/--robot is required when -H/--machine is not provided
        if not parsed.robot:
            dtslogger.error("You need to specify a robot (-R/--robot) - either virtual or real")
            return False
        # sanitize hostnames (lowercase and remove .local)
        parsed.robot = parsed.robot.lower()
        if parsed.robot.endswith(".local"):
            parsed.robot = parsed.robot[:-6]


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

        if parsed.matrix:
            # TODO make sure the matrix is running
            dtslogger.info("Attaching Robot to the Duckiematrix...")
            shell.include.matrix.attach.command(
                shell,
                [parsed.robot, settings.matrix['vehicle'] ],
                parsed=None
            )
            dtslogger.info("Bring up the duckiematrix stack...")
            stack_up_options = ["--machine", parsed.robot, "--detach"]
            success = shell.include.stack.up.command(shell, stack_up_options + ["robot/duckiematrix"])
            if not success:
                dtslogger.error("Problem bringing up duckiematrix stack")


        # sanitize hostnames (lowercase and remove .local)
        if parsed.machine:
            parsed.machine = parsed.machine.lower()
            if parsed.machine.endswith(".local"):
                parsed.machine = parsed.machine[:-6]
        else:
            if not parsed.local:
                parsed.machine = parsed.robot

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)

        project = DTProject(parsed.workdir, recipe.path)

        # collect run arguments (if any)
        run_arg: Dict[str, Any] = {}
        if parsed.launcher:
            # make sure the launcher exists
            if parsed.launcher not in project.launchers:
                dtslogger.error(f"Launcher '{parsed.launcher}' not found in the current project, options are: "
                                f"{project.launchers}")
                return False

        # docker args
        docker_args: List[str] = ["--privileged"]
        # - ros master uri
        docker_args.extend(["-e", f"ROS_MASTER_URI=http://{parsed.robot}.local:11311/"])

        # attach to running container if --shell is requested
        if parsed.shell:
            project = DTProject(parsed.workdir, recipe.path)
            container_name = "dts-run-{:s}".format(project.name)
            dtslogger.info(f"Attaching shell to running container '{container_name}'...")
            run_namespace: SimpleNamespace = SimpleNamespace(
                workdir=parsed.workdir,
                machine=parsed.machine,
                name=container_name,
                subcommand="attach",
            )
            return shell.include.devel.run.command(shell, [], parsed=run_namespace)

        # Run the project using 'devel run'
        run_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            machine=parsed.machine,
            username=parsed.username,
            no_rm=parsed.keep,
            robot=parsed.robot,
            launcher=parsed.launcher,
            docker_args=docker_args,
            **run_arg
        )
        dtslogger.debug(f"Deploying with 'devel/run' using args: {run_namespace}")
        return shell.include.devel.run.command(shell, [], parsed=run_namespace)

    @staticmethod
    def complete(shell, word, line):
        return []


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
