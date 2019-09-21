# This is a default __init__ file for the Duckietown Shell commands
#
# Maintainer: Andrea F. Daniele

# import current command
try:
    # noinspection PyUnresolvedReferences
    from .command import DTCommand

except ImportError:
    pass

import glob

# import subcommands
from os.path import basename, dirname, isdir

modules = glob.glob(dirname(__file__) + "/*")

# load submodules
for mod in [m for m in modules if isdir(m)]:
    try:
        exec("import %s" % basename(mod))
    except ImportError:
        pass
