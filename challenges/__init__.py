from dt_shell import UserError, OtherVersions
from duckietown_challenges import __version__

version = tuple(map(int, __version__.split('.')))
required = (4, 0, 18)

# dtslogger.info(f'Detected duckietown-challenges {__version__} ')

OtherVersions.name2versions['duckietown-challenges'] = __version__


def v(x):
    return ".".join(map(str, x))


if version < required:
    msg = 'Expected duckietown-challenges of at least %s, got %s' % (v(required), v(__version__))
    raise UserError(msg)

from .config import *
from .define import *
from .evaluate import *
from .evaluator import *
from .follow import *
from .info import *
from .list import *
from .reset import *
from .retire import *
from .submit import *
from .auth import *
