# This is a default __init__ file for the Duckietown Shell commands
#
# Maintainer: Andrea F. Daniele

# import current command
try:
    # noinspection PyUnresolvedReferences
    from .command import DTCommand

except ImportError:
    pass

import os
import glob
from os.path import basename, dirname, isdir

modules = glob.glob(dirname(__file__) + "/*")
# this is important to avoid name clashing with commands at lower levels
modules.sort(key=lambda p: int(os.path.isfile(os.path.join(p, 'command.py'))))

# load submodules
for mod in [m for m in modules if isdir(m)]:
    try:
        exec("from .%s import *" % basename(mod))
    except ImportError:
        pass
