from dtproject import DTProject
from dt_shell import dtslogger
from cli.command import _run_cmd

def _run_hooks(hook_name : str, project : DTProject):
    if project.format.version >= 4:
        if len(project.hooks[hook_name]) == 0:
            dtslogger.debug(f"No {hook_name} hooks defined. Skipping hook execution...")
            return

        for hook in project.hooks[hook_name]:
            dtslogger.debug(f"Executing {hook_name} hook: {hook.command}")

            try:
                failed = _run_cmd(hook.command.split(), return_exitcode=True)
            except FileNotFoundError:
                dtslogger.error(f"Hook command '{hook.command}' not found!")
                failed = True

            if failed and hook.required:
                dtslogger.error(f"Required {hook_name} hook failed! Aborting...")
                exit(1)
            elif failed:
                dtslogger.warning(f"{hook_name} hook failed! Continuing...")
    else:
        dtslogger.warning(f"Project format version {project.format.version} does not support hooks. Skipping...")
