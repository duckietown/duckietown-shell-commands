import os
import argparse
from typing import Optional

from dtproject.constants import CANONICAL_ARCH

from dt_shell.commands import DTCommandConfigurationAbs

DEFAULT_TRUE = object()
DEFAULT_NETWORK_MODE = "host"
DEFAULT_REMOTE_USER = "duckie"
DEFAULT_REMOTE_SYNC_LOCATION = "/code"


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        parser = argparse.ArgumentParser()
        parser.add_argument("subcommand", nargs="?", default=None, help="(Optional) Subcommand to execute")
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to run"
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            choices=set(CANONICAL_ARCH.values()),
            help="Target architecture for the image to run",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to run the image",
        )
        parser.add_argument(
            "-R",
            "--robot",
            default=None,
            help="Name of the robot we want this project to connect to",
        )
        parser.add_argument("-n", "--name", default=None, help="Name of the container")
        parser.add_argument("-c", "--cmd", default=None, help="Command to run in the Docker container")
        parser.add_argument(
            "--pull", default=False, action="store_true", help="Whether to pull the image of the project"
        )
        parser.add_argument(
            "--force-pull",
            default=False,
            action="store_true",
            help="Whether to force pull the image of the project",
        )
        parser.add_argument(
            "--build", default=False, action="store_true", help="Whether to build the image of the project"
        )
        parser.add_argument(
            "--plain",
            default=False,
            action="store_true",
            help="Whether to run the image without default module configuration",
        )
        parser.add_argument(
            "--no-multiarch",
            default=False,
            action="store_true",
            help="Whether to disable multiarch support (based on bin_fmt)",
        )
        parser.add_argument(
            "-f",
            "--force",
            default=False,
            action="store_true",
            help="Whether to force the run when the git index is not clean",
        )
        parser.add_argument(
            "-M",
            "--mount",
            default=DEFAULT_TRUE,
            const=True,
            action="store",
            nargs="?",
            type=str,
            help="Whether to mount the current project into the container. "
                 "Pass a comma-separated list of paths to mount multiple projects",
        )
        parser.add_argument(
            "--no-mount",
            default=False,
            action="store_true",
            help="Whether NOT TO mount the current project into the container"
        )
        parser.add_argument(
            "--no-mount-code",
            default=False,
            action="store_true",
            help="Whether NOT TO mount the current project's code into the container"
        )
        parser.add_argument(
            "--no-mount-launchers",
            default=False,
            action="store_true",
            help="Whether NOT TO mount the current project's launchers into the container"
        )
        parser.add_argument(
            "--no-mount-libraries",
            default=False,
            action="store_true",
            help="Whether NOT TO mount the current project's libraries into the container"
        )
        parser.add_argument(
            "--no-impersonate",
            default=False,
            action="store_true",
            help="Do not impersonate the host user inside the container"
        )
        parser.add_argument(
            "--cloud", default=False, action="store_true", help="Run the image on the cloud"
        )
        parser.add_argument(
            "-u",
            "--username",
            default="duckietown",
            help="The docker registry username that owns the Docker image",
        )
        parser.add_argument(
            "--no-rm",
            default=False,
            action="store_true",
            help="Whether to NOT remove the container once stopped",
        )
        parser.add_argument(
            "-L",
            "--launcher",
            default=None,
            help="Launcher to invoke inside the container (template v2 or newer)",
        )
        parser.add_argument(
            "--loop", default=False, action="store_true", help="(Experimental) Whether to run the LOOP image"
        )
        parser.add_argument(
            "--runtime", default="docker", type=str, help="Docker runtime to use to run the container"
        )
        parser.add_argument(
            "-X",
            dest="use_x_docker",
            default=False,
            action="store_true",
            help="Use x-docker as runtime",
        )
        parser.add_argument(
            "-s", "--sync", default=False, action="store_true", help="Sync code from local project to remote"
        )
        parser.add_argument(
            "-su",
            "--sync-user",
            type=str,
            default=DEFAULT_REMOTE_USER,
            help="User on the remote server to sync as"
        )
        parser.add_argument(
            "-sd",
            "--sync-destination",
            type=str,
            default=DEFAULT_REMOTE_SYNC_LOCATION,
            help="Location of the synced code on the remote server"
        )
        parser.add_argument(
            "--net",
            "--network_mode",
            dest="network_mode",
            default=DEFAULT_NETWORK_MODE,
            type=str,
            help="Docker network mode",
        )
        parser.add_argument(
            "-d",
            "--detach",
            default=False,
            action="store_true",
            help="Detach from the container and let it run",
        )
        parser.add_argument(
            "-t",
            "--tag",
            default=None,
            help="Overrides 'version' (usually taken to be branch name)"
        )
        parser.add_argument("docker_args", nargs="*", default=[])
        parser.add_argument(
            "-RW",
            "--read_write",
            default=False,
            action="store_true",
            help="Mount the project in read-write mode",
        )
        # ---
        return parser
