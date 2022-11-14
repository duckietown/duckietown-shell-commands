# This is a default __init__ file for the Duckietown Shell commands
#
# Maintainer: Andrea F. Daniele

import glob as _glob
from os.path import (
    basename as _basename,
    dirname as _dirname,
    exists as _exists,
    isdir as _isdir,
    isfile as _isfile,
    join as _join,
)

# constants
_this_dir = _dirname(__file__)
_command_file = "command.py"

# import current command
if _exists(_join(_this_dir, _command_file)):
    # noinspection PyUnresolvedReferences
    from .command import *

# find all modules
_modules = [m for m in _glob.glob(_join(_this_dir, "*")) if _isdir(m)]
# this is important to avoid name clashing with commands at lower levels
_modules.sort(key=lambda p: int(_isfile(_join(p, _command_file))))

# load submodules
for _mod in _modules:
    try:
        exec("from .%s import *" % _basename(_mod))
    except ImportError as e:
        if _exists(_join(_mod, _command_file)):
            raise EnvironmentError(e)
    except EnvironmentError as e:
        raise e