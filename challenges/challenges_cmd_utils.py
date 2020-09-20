from contextlib import contextmanager

from dt_shell import OtherVersions, UserError


__all__ = ['wrap_server_operations', 'check_duckietown_challenges_version']

def check_duckietown_challenges_version():
    PKG = 'duckietown-challenges-daffy'

    try:
        from duckietown_challenges import __version__
    except ImportError:
        msg = f'Package {PKG} not installed.'
        raise UserError(msg)

    version = tuple(map(int, __version__.split(".")))
    required = (6, 0, 13)

    # dtslogger.info(f'Detected duckietown-challenges {__version__} ')

    OtherVersions.name2versions["duckietown-challenges"] = __version__

    def v(x):
        return ".".join(map(str, x))

    if version < required:
        msg = f"""
    Expected {PKG} of at least {v(required)}, got {v(version)}

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
