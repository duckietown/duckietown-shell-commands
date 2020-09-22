from contextlib import contextmanager

from dt_shell import OtherVersions, UserError

__all__ = ["wrap_server_operations", "check_duckietown_challenges_version"]


def v(x):
    return ".".join(map(str, x))


def check_duckietown_challenges_version():
    PKG = "duckietown-challenges-daffy"
    required = (6, 0, 4)

    PKG_VERSION = v(required)

    try:
        from duckietown_challenges import __version__
    except ImportError:
        msg = f"""
To use the AI-DO commands, you have to have an extra package installed
called `{PKG}`.

You can install it with a command like:

    pip install -U {PKG}>={PKG_VERSION}

(Note: your configuration might require a different command.)
"""
        raise UserError(msg)

    version = tuple(map(int, __version__.split(".")))

    # dtslogger.info(f'Detected duckietown-challenges {__version__} ')

    OtherVersions.name2versions["duckietown-challenges"] = __version__

    if version < required:
        msg = f"""
    To use the AI-DO functionality, you need to have installed
    {PKG} of at least {v(required)}. We have detected you have {v(version)}.

    Please update {PKG} using pip.

        pip install -U  {PKG}>={v(required)}
    """
        raise UserError(msg)


@contextmanager
def wrap_server_operations():
    from duckietown_challenges.rest import NotAuthorized, NotFound, ServerIsDown

    try:
        yield
    except ServerIsDown as e:
        msg = "Server is down; try again later."
        msg += f"\n\n{e}"
        raise UserError(msg) from None

    except NotAuthorized as e:
        # msg = 'You are not authorized to perform the operation.'
        # msg += f'\n\n{e}'
        msg = str(e)
        raise UserError(msg) from None
    except NotFound as e:
        msg = str(e)
        raise UserError(msg) from None
