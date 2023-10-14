import dt_shell
from dt_shell import UserError

__all__ = [
    "ShellNeedsUpdate",
    "InvalidUserInput",
    "RecipeProjectNotFound",
    "SecretNotFound",
    "NetworkingError",
]


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


class InvalidUserInput(UserError):
    pass


class RecipeProjectNotFound(UserError):
    pass


class SecretNotFound(UserError):
    pass


class UserAborted(UserError):
    pass


class NetworkingError(UserError):
    pass
