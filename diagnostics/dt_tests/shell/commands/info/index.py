import update
from diagnostics.utils import DiagnosticsTestAbs, NotSupportedException

class DiagnosticsTest(DiagnosticsTestAbs):

    @staticmethod
    def run_local(shell, args, parsed):
        return {
            'version': update.duckietown_shell_commands_version,
            'config': {
                k: shell.local_commands_info.__dict__[k] for k in shell.local_commands_info.__dict__
            }
        }

    @staticmethod
    def run_robot(shell, args, parsed):
        raise NotSupportedException()
