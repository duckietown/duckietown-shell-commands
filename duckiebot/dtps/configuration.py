import argparse
from typing import List, Optional

from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs


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
        parser = argparse.ArgumentParser("dts duckiebot dtps")
        parser.add_argument(
            "--kv_store",
            default=False,
            action="store_true",
            help="KV store"
        )
        parser.add_argument(
            "--topic",
            default=None,
            type=str,
            help="DTPS topic"
        )
        parser.add_argument(
            "robot",
            help="Robot hostname or IPv4 address (short name, .local name, or FQDN)"
        )
        return parser
