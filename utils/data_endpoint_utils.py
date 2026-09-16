from dt_data_api import DataClient
from dt_data_api.constants import STORAGE_ENDPOINT_URLS
from dt_shell import UserError


ENDPOINT_DATABASE = "data_endpoint"
ENDPOINT_KEY_TEMPLATE = "{space}_storage_endpoint"
DIRECT_ENDPOINT = "direct"
ACCELERATED_ENDPOINT = "accelerated"
STORAGE_ENDPOINTS = (DIRECT_ENDPOINT, ACCELERATED_ENDPOINT)
STORAGE_SPACES = ("user", "public", "private")
PUBLIC_STORAGE_ENDPOINTS = STORAGE_ENDPOINTS


def get_storage_endpoint(shell, space: str) -> str:
    if space not in STORAGE_SPACES:
        raise UserError(f"Unknown storage space '{space}'. Choose one of: {', '.join(STORAGE_SPACES)}.")
    endpoint_key = ENDPOINT_KEY_TEMPLATE.format(space=space)
    endpoint = shell.profile.database(ENDPOINT_DATABASE).get(endpoint_key, DIRECT_ENDPOINT)
    if endpoint not in STORAGE_ENDPOINTS:
        raise UserError(
            f"Invalid endpoint '{endpoint}' for the '{space}' storage space. "
            f"Choose one of: {', '.join(STORAGE_ENDPOINTS)}."
        )
    return endpoint


def set_storage_endpoint(shell, space: str, endpoint: str) -> None:
    if space not in STORAGE_SPACES:
        raise UserError(f"Unknown storage space '{space}'. Choose one of: {', '.join(STORAGE_SPACES)}.")
    if endpoint not in STORAGE_ENDPOINTS:
        raise UserError(
            f"Unknown endpoint '{endpoint}' for the '{space}' storage space. "
            f"Choose one of: {', '.join(STORAGE_ENDPOINTS)}."
        )
    endpoint_key = ENDPOINT_KEY_TEMPLATE.format(space=space)
    shell.profile.database(ENDPOINT_DATABASE).set(endpoint_key, endpoint)


def get_storage_endpoints(shell) -> dict:
    return {space: get_storage_endpoint(shell, space) for space in STORAGE_SPACES}


def get_public_storage_endpoint(shell) -> str:
    return get_storage_endpoint(shell, "public")


def set_public_storage_endpoint(shell, endpoint: str) -> None:
    set_storage_endpoint(shell, "public", endpoint)


def get_public_storage_url(shell, object_path: str) -> str:
    endpoint = get_public_storage_endpoint(shell)
    return STORAGE_ENDPOINT_URLS[endpoint].format(
        bucket="public",
        object=object_path.lstrip("/"),
    )


def create_data_client(shell, token: str = None) -> DataClient:
    return DataClient(token, storage_endpoints=get_storage_endpoints(shell))
