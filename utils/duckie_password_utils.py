import re
import secrets
import string
import subprocess
from typing import Optional

from utils.cli_utils import ensure_command_is_installed


DUCKIE_PASSWORD_MIN_LENGTH = 8
DUCKIE_PASSWORD_SALT_ALPHABET = string.ascii_letters + string.digits + "./"


def validate_duckie_password(password: Optional[str]) -> Optional[str]:
    if not isinstance(password, str) or not password:
        return "--password requires a non-empty value."
    if len(password) < DUCKIE_PASSWORD_MIN_LENGTH:
        return f"--password must be at least {DUCKIE_PASSWORD_MIN_LENGTH} characters long."
    if ":" in password or "\n" in password or "\r" in password:
        return "--password cannot contain colons or line breaks."
    return None


def hash_duckie_password(password: str) -> str:
    ensure_command_is_installed("openssl")
    salt = "".join(secrets.choice(DUCKIE_PASSWORD_SALT_ALPHABET) for _ in range(16))
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-salt", salt, "-stdin"],
        input=password,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Could not hash the duckie user password.")
    password_hash = result.stdout.strip()
    if not re.fullmatch(r"\$6\$[./0-9A-Za-z]{1,16}\$[./0-9A-Za-z]+", password_hash):
        raise RuntimeError("OpenSSL produced an unsupported duckie user password hash.")
    return password_hash
