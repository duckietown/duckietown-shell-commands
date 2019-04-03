from dt_shell import dtslogger
from duckietown_challenges import __version__


version = tuple(map(int, __version__.split('.')))
required = (4, 0, 5)

dtslogger.info(f'Detected duckietown-challenges {__version__} ({version!r}, {required!r}')

def v(x):
    return ".".join(map(str, x))


if version < required:
    msg = 'Expected duckietown-challenges of at least %s, got %s' % (v(required), v(__version__))
    raise Exception(msg)

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
