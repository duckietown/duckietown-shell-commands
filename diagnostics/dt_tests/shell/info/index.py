import dt_shell
from diagnostics.utils import DiagnosticsTestAbs, NotSupportedException

class DiagnosticsTest(DiagnosticsTestAbs):

    @staticmethod
    def run_local(shell, args, parsed):
        result = {
            'version': dt_shell.__version__,
            'config': {
                k: shell.shell_config.__dict__[k] for k in shell.shell_config.__dict__
            }
        }
        result['config']['token_dt1_set'] = True if result['config']['token_dt1'] else False
        del result['config']['token_dt1']
        return result

    @staticmethod
    def run_robot(shell, args, parsed):
        raise NotSupportedException()
