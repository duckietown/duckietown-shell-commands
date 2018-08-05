# import current command
try:
    from .command import *
except ImportError:
    pass

import glob
# import subcommands
from os.path import dirname, basename, isdir

modules = glob.glob(dirname(__file__) + "/*")

# load submodules
for mod in [m for m in modules if isdir(m) and basename(m) != 'lib']:
    exec('import %s' % basename(mod))
