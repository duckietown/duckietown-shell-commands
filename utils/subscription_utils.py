import hashlib
import os
import socket
import time
from datetime import datetime
from json import JSONDecodeError
from logging import Logger

import requests
from dt_authentication import DuckietownToken, GenericException
from dt_shell import DTShell

from requests import HTTPError, RequestException

HUB_URL_PREFIX = os.environ.get("HUB_URL_PREFIX", "hub")
MAX_ATTEMPTS = 2


class SubscriptionRenewalException(BaseException):
    """Exception raised when a subscription renewal fails."""


def can_run_command(shell: DTShell, logger: Logger) -> bool:
    try:
        device_id = _get_device_id(logger)
    except FileNotFoundError:
        logger.error("Device cannot be identified.")
        return False
    except PermissionError:
        logger.error("Permission denied when trying to read '/etc/machine-id'.")
        return False
    except OSError as error:
        logger.error(f"Error accessing '/etc/machine-id': {error}")
        return False
    device_hostname = socket.gethostname()
    secrets = shell.profile.secrets
    dt2_token = DuckietownToken.from_string(secrets.dt2_token)
    data = dt2_token.data
    logger.debug(f"Token data: {data}")
    if data is None:
        try:
            dt2_token = _get_new_dt2_token(dt2_token, device_id, device_hostname, logger)
        except HTTPError:
            logger.error("HTTP error occurred while requesting a new token.")
            return False
        except (GenericException, JSONDecodeError, RequestException) as error:
            logger.error(error)
            return False
        data = dt2_token.data
        logger.debug(f"Token data: {data}")
        secrets.dt2_token = dt2_token.as_string()
    if not data["is_staff"] and not data["is_superuser"]:
        if data["device_id"] is None:
            try:
                dt2_token = _get_new_dt2_token(dt2_token, device_id, device_hostname, logger)
            except HTTPError:
                logger.error("HTTP error occurred while requesting a new token.")
                return False
            except (GenericException, JSONDecodeError, RequestException) as error:
                logger.error(error)
                return False
            data = dt2_token.data
            logger.debug(f"Token data: {data}")
            secrets.dt2_token = dt2_token.as_string()
        if data is None:
            logger.error("Failed to update token or token data is missing.")
            return False
        if data["device_id"] != device_id:
            logger.error("Subscription device limit exceeded.")
            return False
        for attempt in range(MAX_ATTEMPTS):
            try:
                if _has_correct_subscription(dt2_token, attempt, logger):
                    break
                elif attempt == MAX_ATTEMPTS - 1:
                    logger.error(f"This command requires a different subscription. To change your subscription, navigate to https://{HUB_URL_PREFIX}.duckietown.com/subscription-plans/.")
                    return False
            except SubscriptionRenewalException:
                if attempt == MAX_ATTEMPTS - 1:
                    logger.error("Your subscription failed to renew. Please contact support.")
                    return False
            try:
                dt2_token = _get_new_dt2_token(dt2_token, device_id, device_hostname, logger)
            except HTTPError:
                logger.error("HTTP error occurred while requesting a new token.")
                return False
            except (GenericException, JSONDecodeError, RequestException) as error:
                logger.error(error)
                return False
            logger.debug(f"Token data: {dt2_token.data}")
            secrets.dt2_token = dt2_token.as_string()
    logger.debug("All checks passed.")
    return True


def _get_device_id(logger: Logger) -> str:
    logger.debug("Getting device ID...")
    with open("/etc/machine-id") as machine_id_file:
        machine_id = machine_id_file.readline()
    encoded_machine_id = machine_id.encode()
    hashed_machine_id = hashlib.sha256(encoded_machine_id)
    return hashed_machine_id.hexdigest()


def _get_new_dt2_token(dt2_token: DuckietownToken, device_id: str, device_hostname: str, logger: Logger) -> DuckietownToken:
    url = f"https://{HUB_URL_PREFIX}.duckietown.com/api/v1/auth/token/create/"
    dt2_token_string = dt2_token.as_string()
    logger.debug(f"Requesting new token from {url}...")
    response = requests.get(
        url=url,
        params={
            "device_id": device_id,
            "device_hostname": device_hostname,
            "scope": dt2_token.scope,
            "days": 31,
            "hours": 0,
            "minutes": 0,
        },
        headers={
            "Authorization": f"Token {dt2_token_string}"
        },
    )
    response.raise_for_status()
    content = response.json()
    if not content["success"]:
        raise GenericException(content["messages"])
    return DuckietownToken.from_string(content["result"]["token"])


def _has_correct_subscription(dt2_token: DuckietownToken, attempt: int, logger: Logger) -> bool:
    logger.debug(f"{'Rechecking' if attempt > 0 else 'Checking'} subscription status...")
    data = dt2_token.data
    subscription_exp = data["subscription_exp"]
    subscription_expired = time.time() > subscription_exp if subscription_exp is not None else True
    if data["subscription_plan"] == "basic":
        if subscription_expired:
            logger.debug("Incorrect subscription." if subscription_exp is None else "Subscription expired.")
            return False
        subscription_exp_datetime = datetime.fromtimestamp(data["subscription_exp"])
        subscription_exp_datetime_time = subscription_exp_datetime.strftime("%I:%M %p")
        subscription_exp_datetime_date = subscription_exp_datetime.strftime("%B %d, %Y")
        logger.warning(f"Your subscription will expire at {subscription_exp_datetime_time} on {subscription_exp_datetime_date}. To resubscribe, navigate to https://{HUB_URL_PREFIX}.duckietown.com/subscription-plans/.")
        return True
    if subscription_expired:
        raise SubscriptionRenewalException
    return True
