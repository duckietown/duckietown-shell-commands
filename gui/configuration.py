import argparse
from typing import Optional, List

from dt_shell.commands import DTCommandConfigurationAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        parser = argparse.ArgumentParser()
        parser.add_argument("hostname", nargs="?", default=None, help="Name of the Duckiebot")
        parser.add_argument(
            "--network", default="host", help="Name of the network to connect the container to"
        )
        parser.add_argument("--port", action="append", default=[], type=str)
        parser.add_argument(
            "--sim",
            action="store_true",
            default=False,
            help="Are we running in simulator?",
        )
        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Pull the dt-gui-tools image",
        )
        parser.add_argument(
            "--image",
            default=None,
            help="The Docker image to use. Advanced users only.",
        )
        parser.add_argument(
            "--vnc",
            action="store_true",
            default=False,
            help="Run the novnc server",
        )
        parser.add_argument(
            "--ip",
            action="store_true",
            help="(Optional) Use the IP address to reach the robot instead of mDNS",
        )
        parser.add_argument(
            "--mount",
            default=None,
            help="(Optional) Mount a directory to the container",
        )
        parser.add_argument(
            "--wkdir",
            default=None,
            help="(Optional) Working directory inside the container",
        )
        parser.add_argument(
            "-L",
            "--launcher",
            type=str,
            default="default",
            help="(Optional) Launcher to run inside the container",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="(Optional) Container name",
        )
        parser.add_argument(
            "--nvidia",
            action="store_true",
            default=False,
            help="should we use the NVIDIA runtime?",
        )

        parser.add_argument(
            "--uid",
            type=int,
            default=None,
            help="(Optional) User ID inside the container",
        )
        parser.add_argument(
            "--no-scream",
            action="store_true",
            default=False,
            help="(Optional) Scream if the container ends with a non-zero exit code",
        )
        parser.add_argument(
            "--detach",
            "-d",
            action="store_true",
            default=False,
            help="Detach from container",
        )
        parser.add_argument("cmd_args", nargs="*", default=[])
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["start_gui_tools"]
