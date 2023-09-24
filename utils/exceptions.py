import dt_shell
from dt_shell import UserError

__all__ = [
    "ShellNeedsUpdate",
    "InvalidUserInput",
    "RecipeProjectNotFound",
    "SecretNotFound",
    "NetworkingError",
    "UnpinnedDependenciesError"
]

from update import parse_version


class ShellNeedsUpdate(Exception):
    def __init__(self, needed: str):
        self._version_needed: str = needed
        self._current_version: str = dt_shell.__version__

    @property
    def current_version(self) -> str:
        return self._current_version

    @property
    def version_needed(self) -> str:
        return self._version_needed

    @staticmethod
    def assert_newer_or_equal_to(needed: str):
        exc = ShellNeedsUpdate(needed)
        vnow = parse_version(exc.current_version)
        vneed = parse_version(needed)
        if vneed > vnow:
            raise exc


class InvalidUserInput(UserError):
    pass


class RecipeProjectNotFound(UserError):
    pass


class SecretNotFound(UserError):
    pass


class NetworkingError(UserError):
    pass


class UnpinnedDependenciesError(UserError):
    pass
