from typing import Optional, Tuple

from dt_shell import shell as dts_shell
from dt_shell.commands import DTCommandSetConfigurationAbs
from dt_shell.constants import IGNORE_ENVIRONMENTS
from dt_shell.environments import ShellCommandEnvironmentAbs, VirtualPython3Environment

from utils.virtual_robot_alert import register_running_virtual_robot_alert

VERSION: str = "6.0.0"


class DTCommandSetConfiguration(DTCommandSetConfigurationAbs):

    @classmethod
    def default_environment(cls, *args, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        """
        The environment in which the commands in this set will run.
        """
        return VirtualPython3Environment()

    @classmethod
    def version(cls, *args, **kwargs) -> Tuple[int, int, int]:
        """
        Version of this command set in the format (major, minor, patch).
        """
        # noinspection PyTypeChecker
        return tuple(map(int, VERSION.split(".")))

    @classmethod
    def minimum_shell_version(cls, *args, **kwargs) -> Tuple[int, int, int]:
        """
        Minimum version of the shell supported in the format (major, minor, patch).
        """
        return 6, 2, 23

    @classmethod
    def maximum_shell_version(cls, *args, **kwargs) -> Tuple[int, int, int]:
        """
        Maximum version of the shell supported in the format (major, minor, patch).
        """
        return 999, 999, 999


if not IGNORE_ENVIRONMENTS:
    register_running_virtual_robot_alert(dts_shell)
