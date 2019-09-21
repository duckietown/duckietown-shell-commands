from contextlib import contextmanager

from dt_shell import UserError
from duckietown_challenges.rest import NotAuthorized, NotFound, ServerIsDown


@contextmanager
def wrap_server_operations():
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
