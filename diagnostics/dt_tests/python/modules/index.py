import sys
import pip
from diagnostics.utils import DiagnosticsTestAbs, NotSupportedException


class DiagnosticsTest(DiagnosticsTestAbs):

    @staticmethod
    def run_local(shell, args, parsed):
        return {
            'all': sorted([
                "%s==%s" % (m.key, m.version) for m in pip.get_installed_distributions()
            ]),
            'loaded': list(sys.modules.keys())
        }

    @staticmethod
    def run_robot(shell, args, parsed):
        raise NotSupportedException()
