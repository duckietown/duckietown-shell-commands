import argparse
from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs
from typing import Optional, List

class DTCommandConfiguration(DTCommandConfigurationAbs):
    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []

    @classmethod
    def environment(cls, *args, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        """
        The environment in which this command will run.
        """
        return None

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        parser = argparse.ArgumentParser("dts duckiebot dashboard")
        parser.add_argument(
            "--page",
            default=None,
            type=str,
            help="Dashboard page"
        )
        parser.add_argument(
            "robot",
            help="Robot hostname or IPv4 address (short name, .local name, or FQDN)"
        )
        return parser
