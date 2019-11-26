from dt_shell import UserError
from dt_shell.main import OtherVersions
from duckietown_challenges import __version__

version = tuple(map(int, __version__.split(".")))
required = (5, 1, 1)

# dtslogger.info(f'Detected duckietown-challenges {__version__} ')

OtherVersions.name2versions["duckietown-challenges"] = __version__


def v(x):
    return ".".join(map(str, x))


if version < required:
    msg = "Expected duckietown-challenges-daffy of at least %s, got %s" % (
        v(required),
        v(version),
    )
    msg += '\n\nPlease update duckietown-challenges-daffy using pip.'
    msg += '\n\n  pip install -U duckietown-challenges-daffy>=%s' % (v(required))
    raise UserError(msg)
from .challenges_cmd_utils import *
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
