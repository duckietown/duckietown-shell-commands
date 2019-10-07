import sys
from diagnostics.utils import DiagnosticsTestAbs, NotSupportedException

class DiagnosticsTest(DiagnosticsTestAbs):

    @staticmethod
    def run_local(shell, args, parsed):
        return {'version': str(sys.version)}

    @staticmethod
    def run_robot(shell, args, parsed):
        raise NotSupportedException()
