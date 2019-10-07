import json
import subprocess
from diagnostics.utils import DiagnosticsTestAbs, NotSupportedException

class DiagnosticsTest(DiagnosticsTestAbs):

    @staticmethod
    def run_local(shell, args, parsed):
        return DiagnosticsTest._run('unix:///var/run/docker.sock')

    @staticmethod
    def run_robot(shell, args, parsed):
        if parsed.robot:
            return DiagnosticsTest._run(parsed.robot)

    def _run(endpoint):
        cmd = ['docker', '-H', endpoint, 'info', '-f', '{{json .}}']
        res = subprocess.check_output(cmd).decode('utf-8').strip()
        return json.loads(res)
