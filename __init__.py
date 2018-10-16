print('loading commands version 1.0')

import glob
import traceback
# import subcommands
from os.path import dirname, basename, isdir

modules = glob.glob(dirname(__file__) + "/*")

# load submodules
for mod in [m for m in modules if isdir(m) and basename(m) != 'lib']:
    # print('trying to load %r' % m)
    try:
        exec ('import %s' % basename(mod))
    except BaseException as e:
        msg = 'Could not load the command %r' % basename(mod)
        msg += '\n\n' + traceback.format_exc(e)
        print(msg)
