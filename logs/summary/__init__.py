# import current command
try: from .command import *
except ImportError: pass

# import subcommands
from os.path import dirname, basename, isfile, isdir
import glob

modules = glob.glob(dirname(__file__)+"/*")

# load submodules
for mod in [m for m in modules if isdir(m)]:
    exec( 'import %s' % basename(mod) )
