import argparse
from typing import List, Optional

from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs

from utils.duckietown_viewer_utils import SUPPORTED_OS_FAMILIES


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def environment(cls, *args, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        return None

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--app",
            required=True,
            choices=[
                "image_viewer",
                "keyboard_controller",
                "intrinsics_calibrator",
                "extrinsics_calibrator",
                "led_controller",
            ],
            help="Viewer frontend application to launch",
        )
        parser.add_argument(
            "--fullscreen",
            default=False,
            action="store_true",
            help="Run in fullscreen mode",
        )
        parser.add_argument(
            "--menu",
            default=False,
            action="store_true",
            help="Show the application menu bar",
        )
        parser.add_argument(
            "--on-top",
            default=False,
            action="store_true",
            help="Always stay on top of other windows",
        )
        parser.add_argument(
            "--enable-hardware-acceleration",
            default=False,
            action="store_true",
            help="Enable hardware acceleration",
        )
        parser.add_argument(
            "-os",
            "--os-family",
            default="",
            type=str,
            choices=SUPPORTED_OS_FAMILIES,
            help="Run for a given os-family",
        )
        parser.add_argument(
            "--window-arg",
            action="append",
            default=[],
            metavar="KEY=VALUE",
            help="Forward a window argument to the viewer frontend",
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        return []