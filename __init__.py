# XXX none of this is executed

import glob

# import subcommands
from os.path import basename, dirname, isdir

from dt_shell.utils import format_exception
from dt_shell import dtslogger

modules = glob.glob(dirname(__file__) + "/*")

# load submodules
for mod in [m for m in modules if isdir(m) and basename(m) != "lib"]:
    dtslogger.debug(f'trying to load {mod}')
    try:
        exec("import %s" % basename(mod))
    except BaseException as e:
        msg = "Could not load the command %r" % basename(mod)
        msg += "\n\n" + format_exception(e)
        dtslogger.error(msg)
