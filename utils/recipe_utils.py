import os

from dt_shell import UserError
from dt_shell.constants import DTShellConstants


RECIPE_STAGE_NAME = "recipe"
MEAT_STAGE_NAME = "meat"


def get_recipe_project_dir(repository: str, branch: str, location: str) -> str:
    recipes_dir: str = os.path.join(os.path.expanduser(DTShellConstants.ROOT), "recipes")
    return os.path.join(
        os.environ.get("DTSHELL_RECIPES", recipes_dir),
        repository, branch, location.strip("/")
    )


def recipe_project_exists(repository: str, branch: str, location: str) -> bool:
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    return os.path.exists(recipe_dir) and os.path.isdir(recipe_dir)


def clone_recipe(repository: str, branch: str, location: str):
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    if recipe_project_exists(repository, branch, location):
        raise UserError(f"Recipe already exists at '{recipe_dir}'")
    # TODO: @Kathryn, implement this


def update_recipe(repository: str, branch: str, location: str):
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    if not recipe_project_exists(repository, branch, location):
        raise UserError(f"Recipe '{recipe_dir}' has not been cloned yet")
    # TODO: @Kathryn, implement this
