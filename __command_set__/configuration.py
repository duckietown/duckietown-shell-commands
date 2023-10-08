from typing import Optional

from dt_shell.commands import DTCommandSetConfigurationAbs
from dt_shell.environments import Python3Environment, ShellCommandEnvironmentAbs


class DTCommandSetConfiguration(DTCommandSetConfigurationAbs):

    @classmethod
    def default_environment(cls, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        """
        The environment in which the commands in this set will run.
        """
        # return DockerContainerEnvironment("duckietown/dt-shell-commands-environment:ente")
        return Python3Environment()
