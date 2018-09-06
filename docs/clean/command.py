import os
import shutil

from dt_shell import DTCommandAbs


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        pwd = os.getcwd()
        outdir = os.path.join(pwd, 'out')
        if os.path.exists(outdir):
            shutil.rmtree(outdir)
            print('Cleaned intermediate results.')
        else:
            print('No intermediate results found.')
        outdir = os.path.join(pwd, 'duckuments-dist')
        if os.path.exists(outdir):
            shutil.rmtree(outdir)
            print('Cleaned output artifacts.')
        else:
            print('No artifacts found.')
