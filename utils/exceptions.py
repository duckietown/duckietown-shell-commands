from dt_shell import UserError

__all__ = [
    "InvalidUserInput",
    "RecipeProjectNotFound",
    "SecretNotFound",
    "NetworkingError",
    "UnpinnedDependenciesError"
]


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
