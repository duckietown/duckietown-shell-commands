import os

from dt_shell import dtslogger, DTShell


def rename_template(template_dir: str, name: str) -> str:
    """Renames a template directory and decouples from original repo"""
    try:
        mv_dir = template_dir.replace("template-", name, 1)
        dtslogger.debug(f"Moving '{template_dir}' to '{mv_dir}' ...")
        os.rename(template_dir, mv_dir)
        return mv_dir
    except OSError:
        dtslogger.error(f"The template project {mv_dir} already exists.")
        return False
