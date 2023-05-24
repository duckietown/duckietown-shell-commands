import argparse
import copy
import dataclasses
import datetime
import getpass
import grp
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
import traceback
import yaml
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Callable, cast, Dict, List, Optional, Iterable

import requests
from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from duckietown_docker_utils import continuously_monitor
from requests import ReadTimeout

from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import check_program_dependency, start_command_in_subprocess
from utils.docker_utils import (
    get_registry_to_use,
    get_remote_client,
    pull_if_not_exist,
    pull_image,
    remove_if_running,
    get_endpoint_architecture_from_client_OLD,
)
from utils.dtproject_utils import DTProject
from utils.exceptions import InvalidUserInput
from utils.misc_utils import sanitize_hostname, indent_block
from utils.networking_utils import get_duckiebot_ip
from utils.yaml_utils import load_yaml

usage = """

## Basic usage
    This is a helper command to run the workbench portion of a Duckietown Learning Experience (LX).
    You must run this command inside an LX directory.

    To learn more about the Duckietown `code` commands and workflow, use `dts code -h`.

        $ dts code workbench --sim
        $ dts code workbench --duckiebot [DUCKIEBOT_NAME]

"""

# TODO(MOOC): change this to 'daffy'
BRANCH = "daffy"

# TODO: this should be dt-ros-commons instead
ROSCORE_IMAGE = f"duckietown/dt-commons:{BRANCH}"

SIMULATOR_IMAGE = f"duckietown/challenge-aido_lf-simulator-gym:{BRANCH}"
EXPERIMENT_MANAGER_IMAGE = f"duckietown/challenge-aido_lf-experiment_manager:{BRANCH}"
BRIDGE_IMAGE = f"duckietown/dt-duckiebot-fifos-bridge:{BRANCH}"
VNC_IMAGE = f"duckietown/dt-gui-tools:{BRANCH}"

DEFAULT_REMOTE_USER = "duckie"
AGENT_ROS_PORT = "11312"
ROBOT_ROS_PORT = "11311"

ENV_LOGLEVEL = "LOGLEVEL"

# TODO: map to a random port and then ask Docker what port was assigned, this does not scale
PORT_VNC = 8087
# TODO: map to a random port and then ask Docker what port was assigned, this does not scale
PORT_MANAGER = 8090

ROBOT_LOGS_DIR = "/data/logs"
INFTY = 86400


class Levels(Enum):
    LEVEL_NONE = "none"
    LEVEL_DEBUG = "debug"
    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_ERROR = "error"


class ContainerNames(Enum):
    NAME_AGENT = "agent"
    NAME_MANAGER = "manager"
    NAME_SIMULATOR = "simulator"
    NAME_BRIDGE = "bridge"
    NAME_VNC = "vnc"


@dataclass
class ImageRunSpec:
    image_name: str
    environment: Dict
    ports: List[str]


# TODO: register container stopping with `atexit`
# TODO: use `atexit` to cleanup tmp directory


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
    editor: Dict[str, object] = dataclasses.field(default_factory=dict)

    def __str__(self) -> str:
        fields: Iterable[dataclasses.Field] = dataclasses.fields(SettingsFile)
        return "\n\t" + "\n\t".join(f"{field.name}: {getattr(self, field.name)}" for field in fields) + "\n"


def SettingsFile_from_yaml(filename: str) -> SettingsFile:
    data =  load_yaml(filename)
    if not isinstance(data, dict):
        msg = f'Expected that the settings file {filename!r} would be a dictionary, obtained {type(data)}.'
        raise Exception(msg)

    data_dict = cast(Dict[str, object], data)
    known: Dict[str, object] = {
        'agent_base': None,
        'ws_dir': None,
        'log_dir': None,
        'ros': True,
        'step': None,
        'rsync_exclude': [],
        'editor': {},
    }

    params = {}
    for k, default in known.items():
        params[k] = data_dict.get(k, default)

    extra = {}
    for k, v in data_dict.items():
        if k not in known:
            extra[k] = v
    if extra:
        dtslogger.warn(f'Ignoring extra keys {list(extra)} in {filename!r}')

    settings = SettingsFile(**params)

    return settings



ALLOWED_LEVELS = [e.value for e in Levels]
LOG_LEVELS: Dict[ContainerNames, Levels] = {
    ContainerNames.NAME_AGENT: Levels.LEVEL_DEBUG,
    ContainerNames.NAME_MANAGER: Levels.LEVEL_NONE,
    ContainerNames.NAME_SIMULATOR: Levels.LEVEL_NONE,
    ContainerNames.NAME_BRIDGE: Levels.LEVEL_NONE,
    ContainerNames.NAME_VNC: Levels.LEVEL_NONE,
}


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        prog = "dts code workbench"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to bring up"
        )

        parser.add_argument(
            "--duckiebot",
            "-b",
            dest="duckiebot",
            default=None,
            help="Name of the Duckiebot on which to run the exercise",
        )

        parser.add_argument(
            "-s",
            "--simulation",
            "--sim",
            "--simulator",
            action="store_true",
            default=False,
            help="Should we run it in the simulator instead of the real robot?",
        )

        # TODO: this is a weird behavior to have, maybe define `dts code down` ?
        parser.add_argument(
            "--stop",
            dest="stop",
            action="store_true",
            default=False,
            help="Just stop all the containers",
        )

        parser.add_argument(
            "--local",
            "-l",
            dest="local",
            action="store_true",
            default=False,
            help="Should we run the agent locally (i.e. on this machine)? Important Note: "
            + "this is not expected to work on MacOSX",
        )

        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to use if specifying a custom local recipe path",
        )

        parser.add_argument(
            "--recipe-version",
            default=None,
            help="Branch to use if specifying a test branch of the recipes repository",
        )

        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Should we pull all of the images"
        )

        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Ignore the Docker cache"
        )

        parser.add_argument(
            "--bind",
            type=str,
            default="127.0.0.1",
            help="Address to bind to (VNC)",
        )

        loglevels_friendly = " ".join(f"{k.value}:{v}" for k, v in LOG_LEVELS.items())
        parser.add_argument(
            "--logs",
            dest="logs",
            action="append",
            default=[],
            help=f"""
            
            Use --logs NAME:LEVEL to set up levels.
                
            The container names and their defaults are [{loglevels_friendly}].
            
            
            The levels are {', '.join(ALLOWED_LEVELS)}.
            
            """,
        )

        parser.add_argument(
            "--log_dir",
            default=None,
            help="Logging directory",
        )

        parser.add_argument(
            "-L",
            "--launcher",
            default="default",
            help="Launcher to invoke inside the exercise container (advanced users only)",
        )

        parser.add_argument(
            "--registry",
            default=get_registry_to_use(),
            help="Docker registry to use (advanced users only)",
        )

        parser.add_argument(
            "--interactive",
            "-i",
            dest="interactive",
            action="store_true",
            default=False,
            help="Will run the agent in interactive mode with the code mounted",
        )

        parser.add_argument(
            "--keep",
            action="store_true",
            default=False,
            help="Do not auto-remove containers once done. Produces garbage containers but it is "
            "very useful for debugging.",
        )

        parser.add_argument(
            "--sync",
            action="store_true",
            default=False,
            help="RSync code between this computer and the agent",
        )

        parser.add_argument(
            "--challenge",
            help="Run in the environment of this challenge.",
        )

        parser.add_argument(
            "--scenarios",
            type=str,
            help="Uses the scenarios in the given directory.",
        )

        parser.add_argument(
            "--step",
            help="Run this step of the challenge",
        )

        parser.add_argument(
            "--nvidia",
            action="store_true",
            default=False,
            help="Use the NVIDIA runtime (experimental).",
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[""])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

        # make sure we support --nvidia
        if parsed.nvidia:
            try:
                from docker.types import DeviceRequest
            except ImportError:
                dtslogger.error("You need to update the Docker SDK for Python to be able to use the flag "
                                "--nvidia. You can do so with the command:\n\n\tpip3 install -U docker\n")
                exit(1)

        # get information about the host user
        uid = os.getuid()
        username = getpass.getuser()
        auto_remove = not parsed.keep

        # make sense of the '--logs' options
        for line in parsed.logs:
            if ":" not in line:
                msg = f"Malformed option --logs {line}"
                raise UserError(msg)
            name, _, level = line.partition(":")
            name = cast(ContainerNames, name.lower())
            level = cast(Levels, level.lower())
            if name not in LOG_LEVELS:
                msg = f"Invalid container name {name!r}, I know {list(LOG_LEVELS)}"
                raise UserError(msg)
            if level not in ALLOWED_LEVELS:
                msg = f"Invalid log level {level!r}: must be one of {list(ALLOWED_LEVELS)}"
                raise UserError(msg)
            LOG_LEVELS[name] = level
        loglevels_friendly = " ".join(f"{k.value}:{v}" for k, v in LOG_LEVELS.items())
        dtslogger.info(f"Log levels = {loglevels_friendly}")

        # show dtproject info
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        # Make sure the project recipe is present
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
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

        # custom settings
        challenge: str = parsed.challenge or get_challenge_from_submission_file(recipe)
        settings.step = parsed.step or settings.step
        settings.log_dir = parsed.log_dir or settings.log_dir
        dtslogger.info(f"Settings:\n{settings}")

        # variables
        exercise_name = project.name
        use_challenge = challenge is not None
        dtslogger.info(f"Bringing up exercise '{exercise_name}'...")
        if use_challenge:
            dtslogger.info(f"Using rules and scenarios from challenge '{challenge}'")

        # TODO: what is this for?
        # environment directory is in the recipe
        environment_dir = os.path.join(recipe.path, "assets", "environment")
        if parsed.simulation and not os.path.exists(environment_dir):
            msg = "Recipe must contain a 'assets/environment' directory"
            raise InvalidUserInput(msg)

        # # identify agent base image
        # try:
        #     agent_base_image0 = BASELINE_IMAGES[settings.agent_base]
        # except Exception as e:
        #     msg = (
        #         f"Check settings.yaml. Unknown base image {settings.agent_base}. "
        #         f"Available base images are {BASELINE_IMAGES}"
        #     )
        #     raise Exception(msg) from e

        # get the local docker client
        local_client = check_docker_environment()

        # get local architecture
        local_arch: str = get_endpoint_architecture_from_client_OLD(local_client)

        # check user inputs
        duckiebot = parsed.duckiebot
        has_agent: bool = parsed.simulation or parsed.duckiebot

        # - running in simulation forces a local run
        if not parsed.local and parsed.simulation:
            dtslogger.warning("Running locally since we are using simulator")
            parsed.local = True

        # - resolve duckiebot information if we are not using the simulator
        duckiebot_client = duckiebot_hostname = None
        if parsed.duckiebot:
            duckiebot_ip = get_duckiebot_ip(duckiebot)
            duckiebot_client = get_remote_client(duckiebot_ip)
            duckiebot_hostname = sanitize_hostname(duckiebot)

        # agent is local
        agent_is_local: bool = parsed.simulation or parsed.local

        # build agent
        dtslogger.info(f"Building Agent...")
        # Build the project using 'code build' functionality
        build_namespace: SimpleNamespace = SimpleNamespace(
            workdir=project.path,
            machine=None if agent_is_local else duckiebot_hostname,
            username=username,
            no_cache=parsed.no_cache,
            recipe=recipe.path,
            quiet=True
        )
        dtslogger.debug(f"Building with 'code/build' using args: {build_namespace}")
        success: bool = shell.include.code.build.command(shell, [], parsed=build_namespace)
        if not success:
            dtslogger.error("Failed to build the agent image. Aborting.")
            exit(1)

        # sync code with the robot if we are running on a physical robot
        agent_client = local_client
        if not parsed.local:
            if parsed.sync:
                # let's set some things up to run on the Duckiebot
                check_program_dependency("rsync")
                remote_base_path = f"{DEFAULT_REMOTE_USER}@{duckiebot_hostname}:/code/{exercise_name}"
                dtslogger.info(f"Syncing your local folder with {duckiebot}")
                rsync_cmd = "rsync -a "
                for d in settings.rsync_exclude:
                    rsync_cmd += f"--exclude {project.path}/{d} "
                # TODO: no need to sync the recipe, just the meat
                rsync_cmd += f"{project.path}/* {remote_base_path}"
                dtslogger.info(f"rsync command: {rsync_cmd}")
                _run_cmd(rsync_cmd, shell=True)
            # the agent runs on the duckiebot client
            agent_client = duckiebot_client

        # get agent's architecture and image name
        if has_agent:
            agent_arch: str = get_endpoint_architecture_from_client_OLD(agent_client)
            agent_image = project.image(registry=parsed.registry, arch=agent_arch, owner=username)

        # docker container specifications for simulator and experiment manager
        sim_spec: ImageRunSpec
        expman_spec: ImageRunSpec
        if use_challenge:
            # make sure the token is set
            token = shell.shell_config.token_dt1
            if token is None:
                raise UserError("Please set token using the command 'dts tok set'")
            # get container specs from the challenges server
            images = get_challenge_images(challenge=challenge, step=settings.step, token=token)
            sim_spec = images["simulator"]
            expman_spec = images["evaluator"]
        elif parsed.simulation:
            # load container specs from the environment configuration
            sim_env = load_yaml(os.path.join(environment_dir, "sim_env.yaml"))
            sim_spec = ImageRunSpec(
                docker_image(SIMULATOR_IMAGE, parsed.registry), environment=sim_env, ports=[]
            )
            expman_env = load_yaml(os.path.join(environment_dir, "exp_manager_env.yaml"))
            expman_spec = ImageRunSpec(
                docker_image(EXPERIMENT_MANAGER_IMAGE, parsed.registry), environment=expman_env, ports=[]
            )

        # image names
        ros_image = docker_image(ROSCORE_IMAGE, parsed.registry)
        bridge_image = docker_image(BRIDGE_IMAGE, parsed.registry)
        vnc_image = project.image(registry=parsed.registry, arch=local_arch, owner=username, extra="vnc")

        # define container and network names
        prefix = f"ex-{exercise_name}"
        sim_container_name = f"{prefix}-simulator"
        ros_container_name = f"{prefix}-ros"
        vnc_container_name = f"{prefix}-vnc"
        expman_container_name = f"{prefix}-experiment-manager"
        agent_container_name = f"{prefix}-agent"
        bridge_container_name = f"{prefix}-fifos-bridge"
        agent_network_name = f"{prefix}-agent-network"

        # make sure these containers are not running
        # - agent docker engine
        remove_if_running(agent_client, sim_container_name)
        remove_if_running(agent_client, ros_container_name)
        remove_if_running(agent_client, expman_container_name)
        remove_if_running(agent_client, agent_container_name)
        remove_if_running(agent_client, bridge_container_name)
        # - always local engine
        remove_if_running(local_client, vnc_container_name)

        # cleanup unused docker networks
        # noinspection PyBroadException
        try:
            # TODO: this is wrong, we shouldn't bully the user's docker environment this much
            networks = agent_client.networks.prune()
            dtslogger.debug(f"Removed unused docker networks: {networks}")
        except Exception:
            dtslogger.warning(f"Error encountered removing unused docker networks")

        # cleanup unused docker volumes
        # noinspection PyBroadException
        try:
            # TODO: this is wrong, we shouldn't bully the user's docker environment this much
            volumes = agent_client.volumes.prune()
            dtslogger.debug(f"Removed unused docker volumes: {volumes}")
        except Exception:
            dtslogger.warning(f"Error encountered removing unused docker volumes")

        # TODO: odd behavior here
        # if parsed.stop:
        #     dtslogger.info("Only stopping the containers. Exiting.")
        #     return

        # configure ROS environment [TODO: restructure?]
        if parsed.local:
            ros_env = {
                "ROS_MASTER_URI": f"http://{ros_container_name}:{AGENT_ROS_PORT}",
            }
            if parsed.simulation:
                ros_env["VEHICLE_NAME"] = "agent"
                ros_env["HOSTNAME"] = "agent"
            else:
                ros_env["VEHICLE_NAME"] = duckiebot
                ros_env["HOSTNAME"] = duckiebot
        else:
            ros_env = {
                # TODO: use duckiebot_ip in the URL
                "ROS_MASTER_URI": f"http://{duckiebot}.local:{AGENT_ROS_PORT}",
            }

        # update the docker images we will be using (if requested)
        local_images = [expman_spec.image_name, sim_spec.image_name]
        if has_agent:
            agent_images = [bridge_image, ros_image, agent_image]
        else:
            agent_images = []

        if parsed.pull:
            # - pull no matter what
            for image in local_images:
                dtslogger.info(f"Pulling '{image}'...")
                pull_image(image, local_client)
                dtslogger.info(f"Image '{image}' successfully updated!")
            for image in agent_images:
                dtslogger.info(f"Pulling '{image}'...")
                pull_image(image, agent_client)
                dtslogger.info(f"Image '{image}' successfully updated!")
        else:
            # - pull only if they do not exist
            for image in local_images:
                pull_if_not_exist(local_client, image)
            for image in agent_images:
                try:
                    dtslogger.debug(f"pull_if_not_exist(agent_client, '{image}')")
                    pull_if_not_exist(agent_client, image)
                except NotFound:
                    if image == agent_image:
                        dtslogger.error(
                            "Run 'dts code build' to build your agent before running " "the workbench."
                        )
                        exit(1)

        # create a docker network to deploy the containers in
        # noinspection PyBroadException
        try:
            dtslogger.info(f"Creating agent network '{agent_network_name}'...")
            agent_network = agent_client.networks.create(agent_network_name, driver="bridge")
            dtslogger.info(f"Agent network '{agent_network_name}' created successfully!")
        except Exception:
            error: str = traceback.format_exc()
            dtslogger.error(
                "An error occurred while creating the agent network. " f"The error reads: {error}"
            )
            return

        # make temporary directories
        # TODO: use python's temporary directory
        now: str = datetime.datetime.now().strftime("%d%b%y_%H_%M_%S")
        tmpdir = os.path.join("/tmp", username, re.sub(r"[^\w]", "_", prog), now)
        os.makedirs(tmpdir, exist_ok=False)

        # - fifos directory
        fifos_dir = os.path.join(tmpdir, "fifos")
        os.makedirs(fifos_dir, exist_ok=False)

        # - challenges directory
        challenges_dir = os.path.join(tmpdir, "challenges")
        os.makedirs(challenges_dir, exist_ok=False)
        os.makedirs(os.path.join(challenges_dir, "challenge-solution-output"))
        os.makedirs(os.path.join(challenges_dir, "challenge-evaluation-output"))
        os.makedirs(os.path.join(challenges_dir, "challenge-description"))
        os.makedirs(os.path.join(challenges_dir, "tmp"))

        # NOTE: you must create a file in the /challenges mount point because otherwise
        #       the experiment manager will think that something is off
        flag = os.path.join(challenges_dir, "not_empty.txt")
        with open(flag, "w") as f:
            f.write("not_empty")

        # TODO: why?
        # os.sync()
        time.sleep(3)

        # copy challenges specifications to the temporary directory
        challenges_assets_src = os.path.join(environment_dir, "challenges")
        challenges_assets_dst = os.path.join(challenges_dir, "exercise-challenges")
        if os.path.exists(challenges_assets_src):
            shutil.copytree(challenges_assets_src, challenges_assets_dst)
        dtslogger.info(f"Results will be stored in: {challenges_dir}")

        # configure FIFO container
        fifos_bind0 = {fifos_dir: {"bind": "/fifos", "mode": "rw"}}
        if parsed.local:
            # locally, we log in the temporary directory
            agent_challenge_dir = challenges_dir
        else:
            # on the robot, we log in the robots log directory
            agent_challenge_dir = os.path.join(ROBOT_LOGS_DIR, now)

        # bind challenges definition
        challenge_bind0 = {
            agent_challenge_dir: {
                "bind": "/challenges",
                "mode": "rw",
                "propagation": "rshared",
            }
        }

        # agent container takes the challenge definition and the FIFOs
        agent_bind = {
            **challenge_bind0,
            **fifos_bind0,
        }

        # simulator container takes only the FIFOs
        sim_bind = {
            **fifos_bind0,
        }

        # FIFOs bridge container takes the challenge definition and the FIFOs
        bridge_bind = {
            **challenge_bind0,
            **fifos_bind0,
        }

        # experiment manager container takes the whole temporary challenge directory and the FIFOs
        experiment_manager_bind = {
            challenges_dir: {
                "bind": "/challenges",
                "mode": "rw",
                "propagation": "rshared",
            },
            # TODO: this seems wrong, temporary stuff should die with the container
            "/tmp": {"bind": "/tmp", "mode": "rw"},
            **fifos_bind0,
        }

        # custom scenarios
        if parsed.scenarios is not None:
            scenarios = os.path.join(recipe.path, "assets", "scenarios", parsed.scenarios)
            # make sure the directory exists
            if not os.path.exists(scenarios):
                msg = f"Scenario directory does not exist: {scenarios}"
                raise UserError(msg)
            if not os.path.isdir(scenarios):
                msg = f"Need a directory for --scenarios"
                raise UserError(msg)
            # the experiment manager also takes a custom scenario
            experiment_manager_bind[scenarios] = {
                "bind": "/scenarios",
                "mode": "rw",
                "propagation": "rshared",
            }

        # are we running on a mac?
        # TODO: let's build a utility function and an Enum for this, we'll need to support Windows
        if "darwin" in platform.system().lower():
            running_on_mac = True
        else:
            running_on_mac = False

        # keep track of the container to monitor (only detached containers)
        containers_to_monitor = []

        # launch containers
        # - simualator / experiment manager
        if parsed.simulation:

            # TODO: move this to a separate function (similator to launch_bridge)

            dtslogger.info("Running simulator...")
            env = dict(sim_spec.environment)
            # logger level
            if LOG_LEVELS[ContainerNames.NAME_SIMULATOR] != Levels.LEVEL_NONE:
                env[ENV_LOGLEVEL] = LOG_LEVELS[ContainerNames.NAME_SIMULATOR].value
            # simulator container configuration
            sim_params = {
                "image": sim_spec.image_name,
                "name": sim_container_name,
                "network": agent_network.name,  # always local
                "environment": {
                    **env,
                    "USER": username,
                    "UID": uid,
                },
                "volumes": sim_bind,
                "auto_remove": auto_remove,
                "tty": True,
                "detach": True,
            }
            # ---
            dtslogger.debug(
                f"Running simulator container '{sim_container_name}' "
                f"with configuration:\n{json.dumps(sim_params, indent=4)}"
            )
            # pull image if not available
            pull_if_not_exist(agent_client, sim_params["image"])
            # run simulator container
            sim_container = agent_client.containers.run(**sim_params)
            # attach to the logs
            if LOG_LEVELS[ContainerNames.NAME_SIMULATOR] != Levels.LEVEL_NONE:
                threading.Thread(
                    target=continuously_monitor, args=(agent_client, sim_container_name), daemon=True
                ).start()

            # - launch experiment manager

            # TODO: move this to a separate function (similator to launch_bridge)

            dtslogger.info("Running experiment manager...")
            # logger level
            expman_env = copy.deepcopy(expman_spec.environment)
            if LOG_LEVELS[ContainerNames.NAME_MANAGER] != Levels.LEVEL_NONE:
                expman_env[ENV_LOGLEVEL] = LOG_LEVELS[ContainerNames.NAME_MANAGER].value
            # configure ports
            expman_ports = {}
            if use_challenge:
                if expman_spec.ports:
                    the_port = expman_spec.ports[0]
                    expman_ports = {f"{the_port}/tcp": ("0.0.0.0", PORT_MANAGER)}
            else:
                expman_ports = {"8090/tcp": ("0.0.0.0", PORT_MANAGER)}
            # experiment manager container configuration
            expman_params = {
                "image": expman_spec.image_name,
                "name": expman_container_name,
                "environment": {
                    **expman_env,
                    "USER": username,
                    "UID": uid,
                    "submitter_name": username,
                    "submission_id": "0",
                    "challenge_name": exercise_name,
                },
                "ports": expman_ports,
                "network": agent_network.name,
                "volumes": experiment_manager_bind,
                "auto_remove": auto_remove,
                "detach": True,
                "tty": True,
                "user": uid,
            }

            # open configuration
            expman_config = yaml.safe_load(expman_params["environment"]["experiment_manager_parameters"])
            # overwrite experiment manager timeouts
            expman_config["timeout_initialization"] = INFTY
            expman_config["timeout_regular"] = INFTY
            # close configuration
            expman_params["environment"]["experiment_manager_parameters"] = yaml.safe_dump(expman_config)

            # ---
            dtslogger.debug(
                f"Running experiment manager container '{expman_container_name}' "
                f"with configuration:\n{json.dumps(expman_params, indent=4)}"
            )

            dtslogger.info(f"\nSim interface will be running at http://localhost:{PORT_MANAGER}/")
            # pull image if not available
            pull_if_not_exist(agent_client, expman_params["image"])
            # run simulator container
            expman_container = agent_client.containers.run(**expman_params)
            # attach to the logs
            if LOG_LEVELS[ContainerNames.NAME_MANAGER] != Levels.LEVEL_NONE:
                threading.Thread(
                    target=continuously_monitor, args=(agent_client, expman_container_name), daemon=True
                ).start()

            # add containers to monitor to the list (the order matters)
            containers_to_monitor.append(expman_container)
            containers_to_monitor.append(sim_container)

        elif parsed.duckiebot:
            # we are running on a robot instead

            # - launch FIFOs bridge
            bridge_container = launch_bridge(
                bridge_container_name,
                environment_dir,
                duckiebot,
                bridge_bind,
                bridge_image,
                parsed,
                running_on_mac,
                agent_client,
            )
            # add container to monitor to the list (the order matters)
            containers_to_monitor.append(bridge_container)
            # attach to the logs
            if LOG_LEVELS[ContainerNames.NAME_BRIDGE] != Levels.LEVEL_NONE:
                threading.Thread(
                    target=continuously_monitor, args=(agent_client, bridge_container_name), daemon=True
                ).start()

        else:
            # no agent
            pass

        if settings.ros:
            # run ROS core

            # TODO: move this to a separate function (similator to launch_bridge)

            dtslogger.info(f"Running ROS backend...")
            # ROS core container configuration
            ros_params = {
                "image": ros_image,
                "name": ros_container_name,
                "environment": ros_env,
                "detach": True,
                "auto_remove": auto_remove,
                "tty": True,
                "command": f"roscore -p {AGENT_ROS_PORT}",
            }
            # when running on Linux, we need to expose avahi for mDNS to work
            if not running_on_mac:
                ros_params["volumes"] = {
                    "/var/run/avahi-daemon/socket": {
                        "bind": "/var/run/avahi-daemon/socket",
                        "mode": "rw",
                    }
                }
            # configure ROS core container's network
            if parsed.local:
                # local run, attach the ROS core container to the local agent network
                ros_params["network"] = agent_network.name
                ros_params["ports"] = {f"{AGENT_ROS_PORT}/tcp": ("0.0.0.0", AGENT_ROS_PORT)}
            else:
                # running on duckiebot, make ROS core container visible on the host network
                ros_params["network_mode"] = "host"
            # ---
            dtslogger.debug(
                f"Running ROS core container '{ros_container_name}' "
                f"with configuration:\n{json.dumps(ros_params, indent=4)}"
            )
            # pull image if not available
            pull_if_not_exist(agent_client, ros_params["image"])
            # run ros container
            ros_container = agent_client.containers.run(**ros_params)
            # add container to monitor to the list (the order matters)
            containers_to_monitor.append(ros_container)

        # build VNC
        dtslogger.info(f"Building VNC...")
        vnc_namespace: SimpleNamespace = SimpleNamespace(
            workdir=project.path,
            bind=parsed.bind,
            username=username,
            recipe=recipe.path,
            recipe_version=parsed.recipe_version,
            # TODO: test this
            # impersonate=uid,
            build_only=True,
            quiet=True,
        )
        dtslogger.debug(f"Calling command 'code/vnc' with arguments: {str(vnc_namespace)}")
        shell.include.code.vnc.command(shell, [], parsed=vnc_namespace)

        # run VNC
        dtslogger.info(f"Running VNC...")
        # base environment is the ROS environment
        vnc_env = copy.deepcopy(ros_env)
        # when we run the agent locally, set the agent's info explicitly
        if not parsed.local:
            vnc_env["VEHICLE_NAME"] = duckiebot
            vnc_env["ROS_MASTER"] = duckiebot
            vnc_env["HOSTNAME"] = duckiebot

        # TODO: these launchers should be in the assets directory of the recipe
        # vnc_volumes = {
        #     os.path.join(working_dir, "launchers"): {
        #         "bind": "/code/launchers",
        #         "mode": "ro",
        #     }
        # }

        # VNC container configuration
        vnc_params = {
            "image": vnc_image,
            "name": vnc_container_name,
            "command": "dt-launcher-vnc",
            "environment": vnc_env,
            "volumes": {},
            "auto_remove": auto_remove,
            "privileged": True,
            "stream": True,
            "detach": True,
            "tty": True,
        }
        # mount logs directory
        if settings.log_dir:
            local_logs_dir: str = os.path.join(parsed.workdir, settings.log_dir)
            vnc_params["volumes"][local_logs_dir] = {
                "bind": ROBOT_LOGS_DIR,
                "mode": "rw",
            }
        # when running on Linux, we need to expose avahi for mDNS to work
        if not running_on_mac:
            vnc_params["volumes"]["/var/run/avahi-daemon/socket"] = {
                "bind": "/var/run/avahi-daemon/socket",
                "mode": "rw",
            }
        # when running locally, we attach VNC to the agent's network
        if parsed.local:
            vnc_params["network"] = agent_network.name
            # when using --bind, specify the address
            if parsed.bind:
                vnc_params["ports"] = {"8087/tcp": (parsed.bind, 0)}
            else:
                vnc_params["ports"] = {"8087/tcp": ("127.0.0.1", 0)}
        else:
            # when running on the robot, let (local) VNC reach the host network to use ROS
            if not running_on_mac:
                vnc_params["network_mode"] = "host"

        # - mount code (from project (aka meat))
        # get local and remote paths to code
        local_srcs, destination_srcs = project.code_paths()
        # compile mountpoints
        for local_src, destination_src in zip(local_srcs, destination_srcs):
            vnc_params["volumes"][local_src] = {"bind": destination_src, "mode": "rw"}

        # - mount assets (from project (aka meat))
        # get local and remote paths to code
        local_srcs, destination_srcs = project.assets_paths()
        # compile mountpoints
        for local_src, destination_src in zip(local_srcs, destination_srcs):
            vnc_params["volumes"][local_src] = {"bind": destination_src, "mode": "rw"}

        # ---
        dtslogger.debug(
            f"Running VNC container '{vnc_container_name}' "
            f"with configuration:\n{json.dumps(vnc_params, indent=4)}"
        )
        # run vnc container (always runs on local client)
        vnc_container = local_client.containers.run(**vnc_params)
        # add container to monitor to the list (the order matters)
        containers_to_monitor.append(vnc_container)

        # attach to the logs
        if LOG_LEVELS[ContainerNames.NAME_VNC] != Levels.LEVEL_NONE:
            threading.Thread(
                target=continuously_monitor, args=(local_client, vnc_container_name), daemon=True
            ).start()

        # Setup functions for monitor and cleanup
        def stop_attached_container():
            container = agent_client.containers.get(agent_container_name)
            container.reload()
            if container.status == "running":
                container.kill(signal.SIGINT)

        containers_monitor = launch_container_monitor(containers_to_monitor, stop_attached_container)

        # We will catch CTRL+C and cleanup containers

        user_terminated: bool = False

        def handler(_, __):
            nonlocal user_terminated
            user_terminated = True
            clean_shutdown(containers_monitor, containers_to_monitor, stop_attached_container)

        signal.signal(signal.SIGINT, handler)

        # find the port the OS assigned to the container, then print it in 5 seconds
        if not agent_is_local:
            port = str(PORT_VNC)
        else:
            vnc_container.reload()
            ports: Dict[str, List[dict]] = vnc_container.attrs["NetworkSettings"]["Ports"]
            if "8087/tcp" not in ports:
                dtslogger.error(f"VNC ports mismatch: {str(ports)}")
                clean_shutdown(containers_monitor, containers_to_monitor, stop_attached_container)
                return False
            port: str = ports["8087/tcp"][0]["HostPort"]

        def print_nvc_port_later(address="localhost"):
            time.sleep(5)
            space: str = " " * 4
            pspace: str = " " * (4 + (4 - len(port)))
            dtslogger.info(
                f"\n\n\n\n"
                f"================================================================\n"
                f"|                                                              |\n"
                f"|{space}VNC running at http://{address}:{port}{pspace}                  |\n"
                f"|                                                              |\n"
                f"================================================================\n\n\n"
            )

        threading.Thread(target=print_nvc_port_later, args=(parsed.bind,)).start()

        dtslogger.info("Starting attached container")

        if has_agent:
            agent_env = load_yaml(os.path.join(environment_dir, "agent_env.yaml"))
            if settings.ros:
                agent_env = {
                    **ros_env,
                    **agent_env,
                }
                if duckiebot is not None:
                    agent_env.update({
                        "VEHICLE_NAME": duckiebot,
                        "HOSTNAME": duckiebot,
                    })

            if LOG_LEVELS[ContainerNames.NAME_AGENT] != Levels.LEVEL_NONE:
                agent_env[ENV_LOGLEVEL] = LOG_LEVELS[ContainerNames.NAME_AGENT].value

            # build agent (if needed)
            # TODO: check if there is an image with name 'image_name', build one if not

            # TODO: adapt this to 'code/build'
            # # build VNC
            # dtslogger.info(f"Running VNC...")
            # vnc_namespace: SimpleNamespace = SimpleNamespace(
            #     workdir=project.path,
            #     username=username,
            #     recipe=recipe.path,
            #     # TODO: test this
            #     # impersonate=uid,
            #     build_only=True,
            #     quiet=True,
            # )
            # dtslogger.debug(f"Calling command 'code/vnc' with arguments: {str(vnc_namespace)}")
            # shell.include.code.vnc.command(shell, [], parsed=vnc_namespace)
            # TODO: adapt this to 'code/build'

            # attach to the agent container if we are running one

            # noinspection PyBroadException
            try:
                agent_container = launch_agent(
                    project=project,
                    agent_container_name=agent_container_name,
                    agent_volumes=agent_bind,
                    parsed=parsed,
                    agent_base_image=agent_image,
                    agent_network=agent_network,
                    agent_client=agent_client,
                    duckiebot=duckiebot,
                    agent_env=agent_env,
                    tmpdir=tmpdir,
                )

                containers_monitor.add(agent_container)

                attach_cmd = "docker %s attach %s" % (
                    "" if parsed.local else f"-H {duckiebot}.local ",
                    agent_container_name,
                )
                start_command_in_subprocess(attach_cmd)

            except Exception:
                if not user_terminated:
                    dtslogger.error(
                        f"Attached container '{agent_container_name}' terminated:\n"
                        f"{indent_block(traceback.format_exc())}\n"
                    )
            finally:
                clean_shutdown(containers_monitor, containers_to_monitor, stop_attached_container)

        else:

            # if no agent, attach to VNC container

            # noinspection PyBroadException
            try:
                attach_cmd = f"docker attach {vnc_container_name}"
                start_command_in_subprocess(attach_cmd)
            except Exception:
                if not user_terminated:
                    dtslogger.error(
                        f"Attached container '{vnc_container_name}' terminated:\n"
                        f"{indent_block(traceback.format_exc())}\n"
                    )
            finally:
                clean_shutdown(containers_monitor, containers_to_monitor, stop_attached_container)

        dtslogger.info(f"All done, your results are available in: {challenges_dir}")


def clean_shutdown(
    containers_monitor: "ContainersMonitor",
    containers: List[Container],
    stop_attached_container: Callable[[], None],
):
    dtslogger.info("Stopping container monitor...")
    containers_monitor.shutdown()
    while containers_monitor.is_alive():
        time.sleep(1)
    dtslogger.info("Container monitor stopped.")
    # ---
    dtslogger.info("Cleaning containers...")
    workers: List[threading.Thread] = []

    def _stop_container(c: Container):
        try:
            c.stop()
        except NotFound:
            # all is well
            pass
        except APIError as e:
            dtslogger.info(f"Container {container.name} already stopped ({str(e)})")

    for container in containers:
        dtslogger.info(f"Stopping container {container.name}")
        t: threading.Thread = threading.Thread(target=_stop_container, args=(container,))
        t.start()
        workers.append(t)

    for container in containers:
        dtslogger.info(f"Waiting for container {container.name} to stop...")
        try:
            container.wait()
        except (NotFound, APIError, ReadTimeout):
            # all is well
            pass
    # noinspection PyBroadException
    try:
        stop_attached_container()
    except BaseException:
        dtslogger.info(f"attached container already stopped.")


def launch_container_monitor(
    containers_to_monitor: List[Container], stop_attached_container: Callable[[], None]
) -> "ContainersMonitor":
    """
    Start a daemon thread that will exit when the application exits.
    Monitor should stop everything if a containers exits and display logs.
    """
    monitor_thread = ContainersMonitor(containers_to_monitor, stop_attached_container)
    dtslogger.info("Starting monitor thread")
    dtslogger.info(f"Containers to monitor: {list(map(lambda c: c.name, containers_to_monitor))}")
    monitor_thread.start()
    return monitor_thread


class ContainersMonitor(threading.Thread):
    def __init__(self, containers_to_monitor: List[Container], stop_attached_container: Callable[[], None]):
        super().__init__(daemon=True)
        self._containers_to_monitor = containers_to_monitor
        self._stop_attached_container = stop_attached_container
        self._is_shutdown = False
        self._lock = threading.Semaphore()

    def shutdown(self):
        self._is_shutdown = True

    def add(self, container: Container):
        with self._lock:
            self._containers_to_monitor.append(container)

    def run(self):
        """
        When an error is found, we display info and kill the attached thread to stop main process.
        """
        counter = -1
        check_every_secs = 5
        while not self._is_shutdown:
            counter += 1
            if counter % check_every_secs != 0:
                time.sleep(1)
                continue
            # ---
            errors = []

            with self._lock:
                containers = list(self._containers_to_monitor)

            dtslogger.debug(f"{len(containers)} containers to monitor")
            for container in containers:
                try:
                    container.reload()
                except (APIError, TimeoutError) as e:
                    dtslogger.warn(f"Cannot reload container {container.name!r}: {e}")
                    continue
                status = container.status
                dtslogger.debug(f"container {container.name} in state {status}")
                if status in ["exited", "dead"]:
                    errors.append(
                        {
                            "name": container.name,
                            "id": container.id,
                            "status": container.status,
                            "image": container.image.attrs["RepoTags"],
                            "logs": container.logs(),
                        }
                    )
                else:
                    dtslogger.debug("Containers monitor check passed.")

            if errors:
                dtslogger.info(f"Monitor found {len(errors)} exited containers")
                for e in errors:
                    dtslogger.error(
                        f"""Monitored container exited:
                    container: {e['name']}
                    id: {e['id']}
                    status: {e['status']}
                    image: {e['image']}
                    logs: {e['logs'].decode()}
                    """
                    )
                dtslogger.info("Sending kill to container attached container")
                self._stop_attached_container()
            # sleep
            time.sleep(1)


def launch_agent(
    project: DTProject,
    agent_container_name: str,
    agent_volumes: Dict[str, dict],
    parsed: argparse.Namespace,
    agent_base_image: str,
    agent_network,
    agent_client: DockerClient,
    duckiebot: str,
    agent_env: Dict[str, str],
    tmpdir: str,
):
    dtslogger.info(f"Running the {agent_container_name} from {agent_base_image}")
    # get project's recipe (note, it could be the project itself)
    recipe: DTProject = project.recipe if project.needs_recipe else project

    # agent is local
    agent_is_local: bool = parsed.simulation or parsed.local
    agent_is_remote: bool = not agent_is_local

    # - mount code (from project (aka meat))
    if parsed.sync:
        # when we run remotely, use /code/<project> as root
        root = project.path if agent_is_local else f"/code/{project.name}"
        # get local and remote paths to code
        local_srcs, destination_srcs = project.code_paths(root)
        # compile mountpoints
        for local_src, destination_src in zip(local_srcs, destination_srcs):
            if agent_is_remote or os.path.exists(local_src):
                agent_volumes[local_src] = {"bind": destination_src, "mode": "rw"}

    # - mount launchers (from recipe)
    if parsed.sync:
        # when we run remotely, use /launch/<project> as root
        root = recipe.path if agent_is_local else f"/launch/{recipe.name}"
        # get local and remote paths to launchers
        local_launch, destination_launch = recipe.launch_paths(root)
        if agent_is_remote or os.path.exists(local_launch):
            agent_volumes[local_launch] = {"bind": destination_launch, "mode": "rw"}

    # - mount assets (from project (aka meat))
    if agent_is_local:
        # get local and remote paths to assets
        local_srcs, destination_srcs = project.assets_paths()
        # compile mountpoints
        for local_src, destination_src in zip(local_srcs, destination_srcs):
            agent_volumes[local_src] = {"bind": destination_src, "mode": "rw"}

    if not parsed.simulation:
        # define the location of the /data/config to give to the agent
        data = os.path.join(recipe.path, "assets", "agent", "data") if agent_is_local else "/data"

        # get the calibrations from the robot with the REST API
        if parsed.local:
            data = os.path.join(tmpdir, "agent", "data")
            os.makedirs(data)
            # copy /data/config from the robot to a temporary location
            get_calibration_files(data, parsed.duckiebot)

        # add agent's configuration
        agent_volumes[os.path.join(data, "config")] = {"bind": "/data/config", "mode": "rw"}

    # add user to groups if on linux
    on_mac = "Darwin" in platform.system()
    if on_mac:
        group_add = []
    else:
        group_add = [g.gr_gid for g in grp.getgrall() if getpass.getuser() in g.gr_mem]

    agent_env["PYTHONDONTWRITEBYTECODE"] = "1"
    agent_params = {
        "image": agent_base_image,
        "name": agent_container_name,
        "volumes": agent_volumes,
        "environment": agent_env,
        "auto_remove": not parsed.keep,
        "detach": True,
        "tty": True,
        "group_add": group_add,
        "command": [f"dt-launcher-{parsed.launcher}"],
    }

    # disable swappiness
    if agent_is_remote:
        agent_params["mem_swappiness"] = 100

    if parsed.local:
        agent_params["network"] = agent_network.name
    else:
        agent_params["network_mode"] = "host"

    if parsed.interactive:
        agent_params["command"] = "/bin/bash"
        agent_params["stdin_open"] = True

    if parsed.nvidia:
        from docker.types import DeviceRequest
        agent_params["runtime"] = "nvidia"
        agent_params["device_requests"] = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

    # ---
    dtslogger.debug(
        f"Running agent container '{agent_container_name}' "
        f"with configuration:\n{json.dumps(agent_params, indent=4)}"
    )

    if not on_mac:
        # noinspection PyTypeChecker
        agent_params["volumes"]["/var/run/avahi-daemon/socket"] = {
            "bind": "/var/run/avahi-daemon/socket",
            "mode": "rw",
        }

    pull_if_not_exist(agent_client, agent_params["image"])
    agent_container = agent_client.containers.run(**agent_params)

    return agent_container


def launch_bridge(
    bridge_container_name,
    environment_dir,
    duckiebot,
    fifos_bind,
    bridge_image,
    parsed,
    running_on_mac,
    agent_client,
):
    # let's launch the duckiebot fifos bridge, note that this one runs in a different
    # ROS environment, the one on the robot

    dtslogger.info(f"Running {bridge_container_name} from {bridge_image}")
    bridge_env = {
        "HOSTNAME": duckiebot,
        "VEHICLE_NAME": duckiebot,
        "ROS_MASTER_URI": f"http://{duckiebot}.local:{ROBOT_ROS_PORT}",
        **load_yaml(environment_dir + "/duckiebot_bridge_env.yaml"),
    }
    bridge_volumes = fifos_bind
    if not running_on_mac or not parsed.local:
        bridge_volumes["/var/run/avahi-daemon/socket"] = {
            "bind": "/var/run/avahi-daemon/socket",
            "mode": "rw",
        }

    bridge_params = {
        "image": bridge_image,
        "name": bridge_container_name,
        "environment": bridge_env,
        "network_mode": "host",  # bridge always on host
        "volumes": fifos_bind,
        "detach": True,
        "tty": True,
    }

    # if we are local - we need to have a network so that the hostname
    # matches the ROS_MASTER_URI or else ROS complains. If we are running on the
    # Duckiebot we set the hostname to be the duckiebot name so we can use host mode
    if parsed.local and running_on_mac:
        dtslogger.warn(
            "WARNING: Running agent locally not in simulator is not expected to work. "
            "Suggest to remove the --local flag"
        )

    dtslogger.debug(bridge_params)

    pull_if_not_exist(agent_client, bridge_params["image"])
    bridge_container = agent_client.containers.run(**bridge_params)
    return bridge_container


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell and isinstance(cmd, (list, tuple)):
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(cmd, proc.returncode)
                dtslogger.error(msg)
                raise RuntimeError(msg)
        out = proc.stdout.read().decode("utf-8").rstrip()
        if print_output:
            print(out)
        return out
    else:
        try:
            subprocess.check_call(cmd, shell=shell)
        except subprocess.CalledProcessError as e:
            if not suppress_errors:
                raise e


# get the calibration files off the robot
def get_calibration_files(destination_dir, duckiebot):
    dtslogger.info("Getting all calibration files")

    calib_files = [
        "config/calibrations/camera_intrinsic/{duckiebot:s}.yaml",
        "config/calibrations/camera_extrinsic/{duckiebot:s}.yaml",
        "config/calibrations/kinematics/{duckiebot:s}.yaml",
    ]

    for calib_file in calib_files:
        calib_file = calib_file.format(duckiebot=duckiebot)
        url = "http://{:s}.local/files/data/{:s}".format(duckiebot, calib_file)
        # get calibration using the files API
        dtslogger.debug('Fetching file "{:s}"'.format(url))
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            dtslogger.warn(
                "Could not get the calibration file {:s} from robot {:s}. Is it calibrated? "
                "".format(calib_file, duckiebot)
            )
            continue
        # make destination directory
        dirname = os.path.join(destination_dir, os.path.dirname(calib_file))
        if not os.path.isdir(dirname):
            dtslogger.debug('Creating directory "{:s}"'.format(dirname))
            os.makedirs(dirname)
        # save calibration file to disk
        # Also save them to specific robot name for local evaluation
        destination_file = os.path.join(dirname, f"{duckiebot}.yaml")
        dtslogger.debug(
            'Writing calibration file "{:s}:{:s}" to "{:s}"'.format(duckiebot, calib_file, destination_file)
        )
        with open(destination_file, "wb") as fd:
            for chunk in res.iter_content(chunk_size=128):
                fd.write(chunk)


def get_challenge_from_submission_file(recipe: DTProject) -> str:
    # submission file is in the recipe
    submission_file: str = os.path.join(recipe.path, "submission.yaml")
    if not os.path.exists(submission_file):
        msg = "Recipe must contain a 'submission.yaml' file"
        dtslogger.error(msg)
        exit(1)
    submission: dict = load_yaml(submission_file)
    assert len(submission["challenge"]) > 0
    return submission["challenge"][0]


def get_challenge_images(challenge: str, step: Optional[str], token: str) -> Dict[str, ImageRunSpec]:
    default = "https://challenges.duckietown.org/v4"
    server = os.environ.get("DTSERVER", default)
    url = f"{server}/api/challenges/{challenge}/description"
    dtslogger.info(url)
    headers = {"X-Messaging-Token": token}
    res = requests.request("GET", url=url, headers=headers)
    if res.status_code == 404:
        msg = f"Cannot find challenge {challenge} on server; url = {url}"
        raise UserError(msg)
    j = res.json()
    dtslogger.debug(json.dumps(j, indent=1))
    if "result" not in j:
        msg = f"Cannot get data from server at url = {url}"
        raise Exception(msg)
    steps = j["result"]["challenge"]["steps"]
    step_names = list(steps)
    dtslogger.debug(f"steps are {step_names}")
    if step is None:
        step = step_names[0]
    else:
        if step not in step_names:
            msg = f"Wrong step name '{step}'; available {step_names}"
            raise UserError(msg)

    s = steps[step]
    services = s["evaluation_parameters"]["services"]
    res = {}
    for k, v in services.items():
        res[k] = ImageRunSpec(
            image_name=v["image"], environment=v.get("environment", {}), ports=v.get("ports", [])
        )
    return res


def docker_image(image: str, registry: Optional[str]) -> str:
    registry = registry or get_registry_to_use()
    image = image.strip()
    return image if image.startswith(registry) else f"{registry}/{image}"
