import json
import os
import time

from dt_shell import dtslogger
from dt_shell import UserError
from dt_shell import version_check
from dt_shell.constants import DTShellConstants
from dt_shell.utils import run_cmd


RECIPE_STAGE_NAME = "recipe"
MEAT_STAGE_NAME = "meat"
CHECK_RECIPE_UPDATE_MINS = 5


def get_recipes_dir() -> str:
    recipes_dir: str = os.path.join(os.path.expanduser(DTShellConstants.ROOT), "recipes")
    return os.environ.get("DTSHELL_RECIPES", recipes_dir)


def get_recipe_repo_dir(repository: str, branch: str) -> str:
    return os.environ["DTSHELL_RECIPES"] if "DTSHELL_RECIPES" in os.environ else \
        os.path.join(get_recipes_dir(), repository, branch)


def get_recipe_project_dir(repository: str, branch: str, location: str) -> str:
    return os.path.join(get_recipe_repo_dir(repository, branch), location.strip("/"))


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
        repo_dir: str = get_recipe_repo_dir(repository, branch)
        dtslogger.info(f"Downloading recipes...")
        dtslogger.debug(f"Downloading recipes into '{repo_dir}' ...")
        remote_url: str = f"https://github.com/{repository}"
        run_cmd(["git", "clone", "-b", branch, "--recurse-submodules", remote_url, repo_dir])
        dtslogger.info(f"Recipes downloaded!")
        return True
    except Exception as e:
        # Excepts as InvalidRemote
        dtslogger.error(f"Unable to clone the repo '{repository}'. {str(e)}.")
        return False


def recipe_needs_update(repository: str, branch: str, location: str) -> bool:
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    need_update = False
    # Get the current repo info
    commands_update_check_flag = os.path.join(recipe_dir, ".updates-check")

    # Check if it's time to check for an update
    if os.path.exists(commands_update_check_flag) and os.path.isfile(commands_update_check_flag):
        now = time.time()
        last_time_checked = os.path.getmtime(commands_update_check_flag)
        use_cached_recipe = now - last_time_checked < CHECK_RECIPE_UPDATE_MINS * 60
    else:  # Save the initial .update flag
        local_sha: str = run_cmd(["git", "-C", recipe_dir, "rev-parse", "HEAD"])
        # noinspection PyTypeChecker
        local_sha = next(filter(len, local_sha.split("\n")))
        save_update_check_flag(recipe_dir, local_sha)
        return False

    # Check for an updated remote
    if not use_cached_recipe:
        # Get the local sha from file (ok if oos from manual pull)
        with open(commands_update_check_flag, "r") as fp:
            try:
                cached_check = json.load(fp)
            except ValueError:
                return False
            local_sha = cached_check["remote"]

        # Get the remote sha from github
        dtslogger.info("Fetching remote SHA from github.com ...")
        remote_url: str = f"https://api.github.com/repos/{repository}/branches/{branch}"
        try:
            content = version_check.get_url(remote_url)
            data = json.loads(content)
            remote_sha = data["commit"]["sha"]
        except Exception as e:
            dtslogger.error(str(e))
            return False
        # check if we need to update
        need_update = local_sha != remote_sha

    return need_update


def save_update_check_flag(recipe_dir: str, sha: str) -> None:
    commands_update_check_flag = os.path.join(recipe_dir, ".updates-check")
    with open(commands_update_check_flag, "w") as fp:
        json.dump({"remote": sha}, fp)


def update_recipe(repository: str, branch: str, location: str) -> bool:
    recipe_dir: str = get_recipe_project_dir(repository, branch, location)
    if not recipe_project_exists(repository, branch, location):
        raise UserError(f"There is no existing recipe in '{recipe_dir}'.")

    # Check for recipe repo updates
    dtslogger.info("Checking if the project's recipe needs to be updated...")
    if recipe_needs_update(repository, branch, location):
        dtslogger.info("This project's recipe has available updates. Attempting to pull them.")
        dtslogger.debug(f"Updating recipe '{recipe_dir}'...")
        wait_on_retry_secs = 4
        th = {2: "nd", 3: "rd", 4: "th"}
        for trial in range(3):
            try:
                run_cmd(["git", "-C", recipe_dir, "pull", "--recurse-submodules", "origin", branch])
                dtslogger.debug(f"Updated recipe in '{recipe_dir}'.")
                dtslogger.info(f"Recipe successfully updated!")
            except RuntimeError as e:
                dtslogger.error(str(e))
                dtslogger.warning(
                    "An error occurred while pulling the updated commands. Retrying for "
                    f"the {trial + 2}-{th[trial + 2]} in {wait_on_retry_secs} seconds."
                )
                time.sleep(wait_on_retry_secs)
            else:
                break
        run_cmd(["git", "-C", recipe_dir, "submodule", "update"])

        # Get HEAD sha after update and save
        current_sha: str = run_cmd(["git", "-C", recipe_dir, "rev-parse", "HEAD"])
        # noinspection PyTypeChecker
        current_sha = next(filter(len, current_sha.split("\n")))
        save_update_check_flag(recipe_dir, current_sha)
        return True  # Done updating
    else:
        dtslogger.info(f"Recipe is up-to-date.")
        return False
