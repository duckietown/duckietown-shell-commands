import os

from dt_shell import dtslogger
from dt_shell import UserError
from dt_shell.constants import DTShellConstants
from dt_shell.utils import run_cmd


RECIPE_STAGE_NAME = "recipe"
MEAT_STAGE_NAME = "meat"


def get_recipe_project_dir(repository: str, branch: str, location: str) -> str:
    recipes_dir: str = os.path.join(os.path.expanduser(DTShellConstants.ROOT), "recipes")
    return os.path.join(
        os.environ.get("DTSHELL_RECIPES", recipes_dir), repository, location.strip("/")
    )


def get_recipe_repo_dir(repository: str) -> str:
    repo_dir: str = os.path.join(os.path.expanduser(
        DTShellConstants.ROOT), "recipes", repository
    )
    return repo_dir


def recipe_project_exists(repository: str, branch: str, location: str) -> bool:
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    return os.path.exists(recipe_dir) and os.path.isdir(recipe_dir)


def clone_recipe(repository: str, branch: str, location: str) -> bool:
    """
    Args:
        repository: fully qualified name of the repo e.g. duckietown/mooc-exercises
        branch: branch of recipe repo containing the recipe
        location: location of exercise specific recipe
    """
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    if recipe_project_exists(repository, branch, location):
        raise UserError(f"Recipe already exists at '{recipe_dir}'")

    # Clone recipes repo into dt-shell root
    try:
        repo_dir: str = get_recipe_repo_dir(repository)
        dtslogger.info(f"Downloading recipes into '{repo_dir}' ...")
        remote_url: str = f"https://github.com/{repository}"
        run_cmd(["git", "clone", "-b", branch, "--recurse-submodules", remote_url, repo_dir])
        return True
    except Exception as e:
        dtslogger.error(f"Unable to clone the repo '{repository}'. {str(e)}.")
        return False


def update_recipe(repository: str, branch: str, location: str) -> bool:
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    if not recipe_project_exists(repository, branch, location):
        raise UserError(f"Recipe '{recipe_dir}' has not been cloned yet")