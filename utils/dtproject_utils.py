from dtproject import DTProject
from dt_shell import dtslogger
from cli.command import _run_cmd

def _run_hooks(hook_name : str, project : DTProject):
    # Execute post-build hook
    if project.format.version >= 4:
        for hook in project.hooks.hooks[hook_name]:
            dtslogger.debug(f"Executing {hook_name} hook: {hook.command}")
            success = _run_cmd(hook.command, return_exitcode=True)

            if not success and hook.required:
                dtslogger.error(f"{hook_name} hook failed! Aborting...")
                exit(1)
            elif not success:
                dtslogger.warning(f"{hook_name} hook failed! Continuing...")
    else:
        dtslogger.warning(f"Project format version {project.format.version} does not support hooks. Skipping...")
