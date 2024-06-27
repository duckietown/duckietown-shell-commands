from dt_shell import UserError

__all__ = [
    "InvalidUserInput",
    "RecipeProjectNotFound",
    "SecretNotFound",
    "UserAborted",
    "NetworkingError",
    "UnpinnedDependenciesError",
    "NoTracebackException",
]


class UserAborted(UserError):
    pass


class InvalidUserInput(UserError):
    pass


class NoTracebackException(UserError):
    pass


class RecipeProjectNotFound(NoTracebackException):
    pass


class SecretNotFound(NoTracebackException):
    pass


class NetworkingError(NoTracebackException):
    pass


class UnpinnedDependenciesError(NoTracebackException):
    pass
