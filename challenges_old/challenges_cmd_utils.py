from contextlib import contextmanager
from typing import Tuple

from dt_shell import UserError

__all__ = ["wrap_server_operations", "check_duckietown_challenges_version"]


#
# def v(x):
#     return ".".join(map(str, x))

def parse_version(x: str) -> Tuple[int, ...]:
    return tuple(map(int, x.split(".")))


def check_duckietown_challenges_version():
    PKG = "duckietown-challenges-daffy"
    required = "6.0.30"
    check_package_version(PKG, required)


def check_package_version(PKG: str, min_version: str):
    from pip._internal.utils.misc import get_installed_distributions
    installed = get_installed_distributions()
    pkgs = {_.project_name: _ for _ in installed}
    if PKG not in pkgs:
        msg = f"""
        You need to have an extra package installed called `{PKG}`.

        You can install it with a command like:

            pip install -U "{PKG}>={min_version}"

        (Note: your configuration might require a different command.)
        """
        raise UserError(msg)

    p = pkgs[PKG]

    installed_version = parse_version(p.version)
    required_version = parse_version(min_version)
    if installed_version < required_version:
        msg = f"""
       You need to have installed {PKG} of at least {min_version}. 
       We have detected you have {p.version}.

       Please update {PKG} using pip.

           pip install -U  "{PKG}>={min_version}"

       (Note: your configuration might require a different command.)
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
