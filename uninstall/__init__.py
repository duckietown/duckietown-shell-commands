# This is a default __init__ file for the Duckietown Shell commands
#
# Maintainer: Andrea F. Daniele

# import current command
try: from .command import *
except ImportError: pass

# import subcommands
from os.path import dirname, basename, isfile, isdir
import glob

modules = glob.glob(dirname(__file__)+"/*")

# load submodules
for mod in [m for m in modules if isdir(m)]:
    try: exec( 'import %s' % basename(mod) )
    except ImportError: pass
