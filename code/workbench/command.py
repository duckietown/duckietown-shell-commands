import dataclasses
import os
from types import SimpleNamespace
from typing import Dict, Any, cast, Iterable, List, Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell
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

        # -R/--robot is required when -H/--machine is not provided
        if not parsed.machine and not parsed.robot:
            dtslogger.error("You need to specify either a machine (-H/--machine) or a robot (-R/--robot)")
            return False

        # sanitize hostnames (lowercase and remove .local)
        if parsed.machine:
            parsed.machine = parsed.machine.lower()
            if parsed.machine.endswith(".local"):
                parsed.machine = parsed.machine[:-6]

        # sanitize hostnames (lowercase and remove .local)
        if parsed.robot:
            parsed.robot = parsed.robot.lower()
            if parsed.robot.endswith(".local"):
                parsed.robot = parsed.robot[:-6]

        # if no robot is provided, use the machine name
        if not parsed.robot:
            parsed.robot = parsed.machine

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # collect run arguments (if any)
        run_arg: Dict[str, Any] = {}
        # - launcher
        if parsed.launcher:
            # make sure the launcher exists
            if parsed.launcher not in project.launchers:
                dtslogger.error(f"Launcher '{parsed.launcher}' not found in the current project")
                return False

        # docker args
        docker_args: List[str] = []
        # - ros master uri
        docker_args.extend(["-e", f"ROS_MASTER_URI=http://{parsed.robot}.local:11311/"])

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
    # agent base image
    # TODO: do we still need this?
    agent_base: Optional[str] = None

    # directory that contains the code the user needs to see
    # TODO: do we still need this?
    ws_dir: Optional[str] = None

    # directory that we should mount to put logs in
    # TODO: do we still need this?
    log_dir: Optional[str] = None

    # whether the project uses ROS
    # TODO: do we still need this?
    ros: Optional[bool] = True

    # TODO: not sure what this is
    # TODO: do we still need this?
    step: Optional[str] = None

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
        "agent_base": None,
        "ws_dir": None,
        "log_dir": None,
        "ros": True,
        "step": None,
        "rsync_exclude": [],
        "editor": {},
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
