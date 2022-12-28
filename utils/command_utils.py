from types import SimpleNamespace

from dt_shell import DTCommandAbs, dtslogger


class NoOpCommand(DTCommandAbs):
    @staticmethod
    def command(shell, args, **kwargs):
        pass


class FailedToLoadCommand(NoOpCommand):
    @staticmethod
    def command(shell, args, **kwargs):
        dtslogger.warning("This command was not loaded")


noop_command = SimpleNamespace(DTCommand=NoOpCommand)
failed_to_load_command = SimpleNamespace(DTCommand=FailedToLoadCommand)


__all__ = ["noop_command", "failed_to_load_command"]
