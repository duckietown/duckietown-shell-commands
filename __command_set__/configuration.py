from typing import Optional

from dt_shell.commands import DTCommandSetConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs, VirtualPython3Environment


class DTCommandSetConfiguration(DTCommandSetConfigurationAbs):

    @classmethod
    def default_environment(cls, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        """
        The environment in which the commands in this set will run.
        """
        return VirtualPython3Environment()
