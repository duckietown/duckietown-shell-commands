# This is a default __init__ file for the Duckietown Shell commands
#
# Maintainer: Andrea F. Daniele

# import current command
try:
    from .command import *
except ImportError:
    pass

import glob
from os.path import dirname, basename, isdir

modules = glob.glob(dirname(__file__) + "/*")

# load submodules
for mod in [m for m in modules if isdir(m)]:
    try:
        exec('from .%s import *' % basename(mod))
    except ImportError:
        pass
