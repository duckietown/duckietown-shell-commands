# Maintainer: Andrea F. Daniele, Luzian Bieri


from dt_shell import dtslogger

try:
    import paramiko
    import scp
    import asyncio
    import ptyprocess
    import nest_asyncio
    import argparse

except ImportError:
    msg = """need to install the following packages:
paramiko
scp
asyncio
ptyprocess
nest_asyncio
argparse

do so my executing:
$ pip3 install paramiko scp asyncio ptyprocess nest_asyncio argparse

    """
    dtslogger.error(msg)
    exit()

from os.path import \
    exists as _exists, \
    dirname as _dirname, \
    basename as _basename, \
    isdir as _isdir, \
    join as _join
import glob as _glob

# constants
_this_dir = _dirname(__file__)
_command_file = "command.py"

# import current command
if _exists(_join(_this_dir, _command_file)):
    from .command import *

# find all modules
_modules = [m for m in _glob.glob(_join(_this_dir, "*")) if _isdir(m)]

# load submodules
for _mod in _modules:
    try:
        exec('from .%s import *' % _basename(_mod))
    except ImportError as e:
        if _exists(_join(_mod, _command_file)):
            raise EnvironmentError(e)
    except EnvironmentError as e:
        raise e
