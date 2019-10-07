import subprocess
from diagnostics.utils import DiagnosticsTestAbs, NotSupportedException

DOCKER_PS_FORMAT = '{"id" : "{{.ID}}", "image" : "{{.Image}}", "command" : {{.Command}}, "created_at" : "{{.CreatedAt}}", "running_for" : "{{.RunningFor}}", "ports" : "{{.Ports}}", "status" : "{{.Status}}", "size" : "{{.Size}}", "names" : "{{.Names}}", "labels" : "{{.Labels}}", "mounts" : "{{.Mounts}}", "networks" : "{{.Networks}}"}'

class DiagnosticsTest(DiagnosticsTestAbs):

    @staticmethod
    def run_local(shell, args, parsed):
        return DiagnosticsTest._run('unix:///var/run/docker.sock')

    @staticmethod
    def run_robot(shell, args, parsed):
        if parsed.robot:
            return DiagnosticsTest._run(parsed.robot)

    def _run(endpoint):
        cmd = ['docker', '-H', endpoint, 'ps', '--all', '--format', DOCKER_PS_FORMAT]
        res = subprocess.check_output(cmd).decode('utf-8').strip()
        containers = [eval(s) for s in res.split('\n')]
        return containers
