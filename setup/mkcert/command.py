import argparse
import os
import platform
import stat
import subprocess

from pathlib import Path
from typing import List
from subprocess import STDOUT

import requests
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.constants import DTShellConstants

from utils.dtproject_utils import CANONICAL_ARCH

MKCERT_VERSION = "1.4.4"
LOCAL_DOMAIN = "localhost"


class DTCommand(DTCommandAbs):
    help = 'Creates a local certificate authority and registers it against the OS trust stores'

    @staticmethod
    def command(shell: DTShell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--uninstall",
            default=False,
            action="store_true",
            help="Uninstall local Certificate Authority from trust stores"
        )
        parsed = parser.parse_args(args=args)
        # define location for SSL certificate and key
        root: str = os.path.expanduser(DTShellConstants.ROOT)
        ca_dir: str = os.path.join(root, "secrets", "mkcert", "ca")
        ssl_dir: str = os.path.join(root, "secrets", "mkcert", "ssl")
        cmd_env = {"CAROOT": ca_dir}
        env = {**os.environ, **cmd_env}

        # install mkcert (if needed)
        DTCommand._install_mkcert()

        # uninstall
        if parsed.uninstall:
            dtslogger.info(f"Uninstalling Certificate Authority, you might be prompted to "
                           f"insert your sudo password...")
            cmd: List[str] = DTCommand._mkcert_command("-uninstall")
            dtslogger.debug(f"Running command:\n\t$ {cmd}\n\tenv: {cmd_env}\n")
            subprocess.check_call(cmd, env=env)
            return

        # create local certificate authority and domain certificate (if needed)
        # - make sure the directory exists
        os.makedirs(ca_dir, exist_ok=True)
        # - define CA files
        ca_cert: str = os.path.join(ca_dir, "rootCA.pem")
        ca_key: str = os.path.join(ca_dir, "rootCA-key.pem")
        ca_exists: bool = os.path.exists(ca_cert) and os.path.exists(ca_key)

        # - make certificate authority and install
        if not ca_exists:
            dtslogger.info("Creating and installing a new local Certificate Authority, "
                           "you might be prompted to insert your sudo password...")
            cmd: List[str] = DTCommand._mkcert_command("-install")
            dtslogger.debug(f"Running command:\n\t$ {cmd}\n\tenv: {cmd_env}\n")
            out = subprocess.check_output(cmd, env=env, stderr=STDOUT).decode("utf-8")
            print(out)
            # make sure the CA was created
            if "Created a new local CA" not in out:
                raise Exception(f"An error occurred while creating a local CA:\n\n{out}")
            assert os.path.exists(ca_cert)
            assert os.path.exists(ca_key)
            # make sure the CA was installed
            installed: bool = "the local CA is not installed" not in out
            if not installed:
                raise Exception(f"An error occurred while installing the local CA:\n\n{out}")
            # ---
            dtslogger.info("A new local Certificate Authority was successfully installed.")
        else:
            dtslogger.info(f"Existing local Certificate Authority found in [{ca_dir}]")

        # create domain certificate key pair (if needed)
        # - make sure the directory exists
        os.makedirs(ssl_dir, exist_ok=True)
        # - make domain certificate
        ssl_cert: str = os.path.join(ssl_dir, f"{LOCAL_DOMAIN}.pem")
        ssl_key: str = os.path.join(ssl_dir, f"{LOCAL_DOMAIN}-key.pem")
        ssl_exists: bool = os.path.exists(ssl_cert) and os.path.exists(ssl_key)

        # - make domain certificate
        if not ssl_exists:
            dtslogger.info(f"Creating local certificate for the domain '{LOCAL_DOMAIN}'...")
            cmd: List[str] = DTCommand._mkcert_command(
                "-cert-file", ssl_cert, "-key-file", ssl_key, LOCAL_DOMAIN
            )
            dtslogger.debug(f"Running command:\n\t$ {cmd}\n\tenv: {cmd_env}\n")
            out = subprocess.check_output(cmd, env=env, stderr=STDOUT).decode("utf-8")
            print(out)
            # make sure the domain certificate was created
            if "Created a new certificate valid for the following names" not in out:
                raise Exception(f"An error occurred while creating a domain certificate:\n\n{out}")
            assert os.path.exists(ssl_cert)
            assert os.path.exists(ssl_key)
            # ---
            dtslogger.info(f"A new certificate for the domain '{LOCAL_DOMAIN}' was created.")
        else:
            dtslogger.info(f"Existing domain certificate found in [{ssl_dir}]")

    @staticmethod
    def _get_mkcert_bin_url() -> str:
        system = platform.system().lower()
        machine = platform.machine()
        if system not in ["darwin", "linux", "windows"]:
            raise ValueError(f"System '{system}' not supported")
        if machine not in CANONICAL_ARCH:
            raise ValueError(f"Architecture not supported '{machine}'")
        arch = {
            "amd64": "amd64",
            "arm32v7": "arm",
            "arm64v8": "arm64"
        }[CANONICAL_ARCH[machine]]
        ext = {
            "darwin": "",
            "linux": "",
            "windows": ".exe",
        }[system]
        return f"https://github.com/FiloSottile/mkcert/releases/download/" \
               f"v{MKCERT_VERSION}/mkcert-v{MKCERT_VERSION}-{system}-{arch}{ext}"

    @staticmethod
    def _install_mkcert():
        # make bin directory
        root: str = os.path.expanduser(DTShellConstants.ROOT)
        bin_dir: str = os.path.join(root, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        # do nothing if mkcert can be found locally
        bin: str = os.path.join(bin_dir, "mkcert")
        if os.path.exists(bin):
            dtslogger.debug(f"Binary for `mkcert` found at '{bin}'")
            return
        # download mkcert binary
        url: str = DTCommand._get_mkcert_bin_url()
        dtslogger.info(f"Downloading mkcert...")
        dtslogger.debug(f"Downloading binary [{url}] -> [{bin}]...")
        res = requests.get(url)
        with open(bin, "wb") as fout:
            fout.write(res.content)
        # make binary executable
        f = Path(bin)
        dtslogger.debug(f"Making [{bin}] executable")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    @staticmethod
    def _mkcert_command(*args) -> List[str]:
        root: str = os.path.expanduser(DTShellConstants.ROOT)
        bin_dir: str = os.path.join(root, "bin")
        bin: str = os.path.join(bin_dir, "mkcert")
        assert os.path.exists(bin)
        return [bin, *args]

    @staticmethod
    def complete(shell, word, line):
        return []
