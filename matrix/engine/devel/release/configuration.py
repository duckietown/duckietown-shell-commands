import argparse

from dt_shell.commands import DTCommandConfigurationAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):
    @classmethod
    def environment(cls, *args, **kwargs):
        return None

    @classmethod
    def parser(cls, *args, **kwargs):
        parser = argparse.ArgumentParser(prog="dts matrix engine devel release")
        parser.add_argument("--file", required=True, help="Signed engines.json from the protected Engine release workflow")
        parser.add_argument("--token", default=None, help="Optional publisher identity for DCSS uploads")
        parser.add_argument("--force", default=False, action="store_true", help="Explicitly approve replacement or rollback")
        return parser
