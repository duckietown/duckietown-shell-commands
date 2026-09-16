import getpass
import re
import warnings

from passlib.hash import sha512_crypt

DUCKIE_PASSWORD_MIN_LENGTH = 8
DUCKIE_PASSWORD_HASH_ROUNDS = 5000
DUCKIE_PASSWORD_SALT_SIZE = 16


def validate_duckie_password(password: str | None) -> str | None:
    if not isinstance(password, str) or not password:
        return "Password cannot be empty."
    if len(password) < DUCKIE_PASSWORD_MIN_LENGTH:
        return f"Password must be at least {DUCKIE_PASSWORD_MIN_LENGTH} characters long."
    if ":" in password or "\n" in password or "\r" in password:
        return "Password cannot contain colons or line breaks."
    return None


def prompt_and_hash_duckie_password() -> str:
    while True:
        password = _read_hidden_password("Password for the robot's duckie user: ")
        if validate_duckie_password(password) is not None:
            print(
                "Invalid password. It must contain at least 8 characters and cannot "
                "contain colons or line breaks. Please try again."
            )
            continue

        confirmation = _read_hidden_password(
            "Confirm password for the robot's duckie user: "
        )
        if password == confirmation:
            return hash_duckie_password(password)

        print("Passwords do not match. Please try again.")


def _read_hidden_password(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning as error:
            raise RuntimeError(
                "Cannot securely read a password without an interactive terminal."
            ) from error


def hash_duckie_password(password: str) -> str:
    password_hash = sha512_crypt.using(
        rounds=DUCKIE_PASSWORD_HASH_ROUNDS,
        salt_size=DUCKIE_PASSWORD_SALT_SIZE,
    ).hash(password)
    if not re.fullmatch(r"\$6\$[./0-9A-Za-z]{1,16}\$[./0-9A-Za-z]+", password_hash):
        raise RuntimeError("Password hashing produced an unsupported duckie user password hash.")
    return password_hash
