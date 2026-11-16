import os
import subprocess
from pathlib import Path

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.host_runner import delegate_matrix_capture_to_host, should_delegate_to_host
from utils.matrix_capture import (
    CAPTURE_OUTPUT_ENV,
    capture_matrix,
    resolve_capture_output,
    validate_capture_options,
)


class DTCommand(DTCommandAbs):

    help = "Captures and analyses a native macOS Renderer with Apple's headless GPU tools"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        try:
            validate_capture_options(parsed)
            host_output = os.environ.get(CAPTURE_OUTPUT_ENV)
            output = resolve_capture_output(host_output or parsed.output)
            if should_delegate_to_host():
                code = delegate_matrix_capture_to_host(parsed, output)
                if code:
                    raise SystemExit(code)
            else:
                capture_matrix(parsed, output)
                if host_output:
                    (Path(host_output).parent / "complete").touch(exist_ok=False)
            dtslogger.info(f"Metal capture results: {output}")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            dtslogger.error(f"Metal capture failed: {error}")
            raise SystemExit(1) from error

    @staticmethod
    def complete(shell, word, line):
        return []
