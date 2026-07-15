import argparse
import datetime
import tempfile
import os
import platform
import stat
import subprocess

from pathlib import Path
from typing import List
from subprocess import STDOUT

from os.path import join, exists, expanduser

import requests
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.constants import DTShellConstants

from dtproject.constants import CANONICAL_ARCH

MKCERT_VERSION = "1.4.4"
LOCAL_DOMAIN = "localhost"
LOCAL_IP = "127.0.0.1"


class DTCommand(DTCommandAbs):
    help = "Creates a local certificate authority and registers it against the OS trust stores"

    @staticmethod
    def command(shell: DTShell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--uninstall",
            default=False,
            action="store_true",
            help="Uninstall local Certificate Authority from trust stores",
        )
        parsed = parser.parse_args(args=args)
        # define location for SSL certificate and key
        root: str = expanduser(DTShellConstants.ROOT)
        default_ca_dir: str = join(root, "secrets", "mkcert", "ca")
        os.makedirs(default_ca_dir, exist_ok=True)
        # check if CAROOT is already set and use it
        ca_variable_name = "CAROOT"
        using_external_caroot = False
        if ca_variable_name in os.environ and os.environ[ca_variable_name]:
            external_ca_dir: str = os.environ.get(ca_variable_name)
            external_ca_cert: str = join(external_ca_dir, "rootCA.pem")
            external_ca_key: str = join(external_ca_dir, "rootCA-key.pem")
            external_ca_exists: bool = exists(external_ca_cert) and exists(external_ca_key)
            external_ca_writable: bool = os.access(external_ca_dir, os.W_OK)
            if external_ca_exists or external_ca_writable:
                ca_dir = external_ca_dir
                using_external_caroot = True
                if external_ca_exists:
                    dtslogger.info(f"An existing local Certificate Authority is already installed in {ca_dir}.")
                else:
                    dtslogger.info(f"Using writable external Certificate Authority directory {ca_dir}.")
            else:
                ca_dir = default_ca_dir
                dtslogger.warning(
                    f"Ignoring {ca_variable_name}={external_ca_dir}: the directory does not contain a complete "
                    f"mkcert CA and is not writable. Falling back to {ca_dir}."
                )
        else:
            ca_dir = default_ca_dir

        ssl_dir: str = join(root, "secrets", "mkcert", "ssl")
        cmd_env = {ca_variable_name: ca_dir}

        env = {**os.environ, **cmd_env}

        # install mkcert (if needed)
        DTCommand._install_mkcert()

        # create local certificate authority and domain certificate (if needed)
        # - define CA files
        ca_cert: str = join(ca_dir, "rootCA.pem")
        ca_key: str = join(ca_dir, "rootCA-key.pem")
        ca_flag: str = join(ca_dir, "rootCA-key.installed")
        # If using external CAROOT, skip flag check as directory might be read-only
        if using_external_caroot:
            ca_exists: bool = exists(ca_cert) and exists(ca_key)
        else:
            ca_exists: bool = exists(ca_flag) and exists(ca_cert) and exists(ca_key)

        # uninstall
        if parsed.uninstall:
            dtslogger.info(
                f"Uninstalling Certificate Authority, you might be prompted to "
                f"insert your sudo password..."
            )
            cmd: List[str] = DTCommand._mkcert_command("-uninstall")
            dtslogger.debug(f"Running command:\n\t$ {cmd}\n\tenv: {cmd_env}\n")
            subprocess.check_call(cmd, env=env)
            # Only try to remove flag file if we're not using external CAROOT (might be read-only)
            if not using_external_caroot:
                try:
                    os.remove(ca_flag)
                    print(f"File '{ca_flag}' deleted successfully.")
                except OSError as e:
                    print(f"Error occurred while deleting the file: {e}")
            return

        # - make certificate authority and install
        if not ca_exists:
            dtslogger.info(
                "Installing a new local Certificate Authority, "
                "you might be prompted to insert your sudo password..."
            )
            cmd: List[str] = DTCommand._mkcert_command("-install")
            dtslogger.debug(f"Running command:\n\t$ {cmd}\n\tenv: {cmd_env}\n")
            out = subprocess.check_output(cmd, env=env, stderr=STDOUT).decode("utf-8")
            # make sure the CA was created
            if (
                "Created a new local CA" not in out
                and "The local CA is already installed" not in out
                and "The local CA is now installed" not in out
            ):
                raise Exception(f"An error occurred while creating a local CA:\n\n{out}")

            assert exists(ca_cert)
            assert exists(ca_key)
            # look for missing libraries
            # - linux
            if "libnss3-tools" in out:
                dtslogger.error(
                    "The system library 'libnss3-tools' is missing, please, "
                    "install it using the following command and the retry:\n\n"
                    "\t$ sudo apt install libnss3-tools\n\n"
                )
                exit(1)
            # - mac osx
            if "brew install nss" in out:
                dtslogger.error(
                    "The system library 'nss' is missing, please, "
                    "install it using the following command and the retry:\n\n"
                    "\t$ brew install nss\n\n"
                )
                exit(1)
            print(out)
            # make sure the CA was installed
            installed: bool = "the local CA is not installed" not in out
            if not installed:
                raise Exception(f"An error occurred while installing the local CA:\n\n{out}")
            # ---
            # Only write the flag file if we're not using external CAROOT (might be read-only)
            if not using_external_caroot:
                with open(ca_flag, "wt") as fout:
                    fout.write(str(datetime.datetime.now().isoformat()))
            dtslogger.info("A new local Certificate Authority was successfully installed.")
        else:
            dtslogger.info(f"Existing local Certificate Authority found in [{ca_dir}]")

        # create domain certificate key pair (if needed)
        # - make sure the directory exists
        os.makedirs(ssl_dir, exist_ok=True)
        # - make domain certificate
        ssl_cert: str = join(ssl_dir, f"{LOCAL_DOMAIN}.pem")
        ssl_key: str = join(ssl_dir, f"{LOCAL_DOMAIN}-key.pem")
        ssl_exists: bool = exists(ssl_cert) and exists(ssl_key)
        ssl_valid_for_ca: bool = False
        if ssl_exists:
            ssl_valid_for_ca, _ = DTCommand.certificate_valid_for_ca(ssl_cert, ca_cert)

        # - make domain certificate
        if not ssl_exists or not ssl_valid_for_ca:
            if ssl_exists:
                dtslogger.warning(
                    f"Existing domain certificate found in [{ssl_dir}] but it is not signed by the current "
                    f"Certificate Authority [{ca_cert}]. Regenerating it."
                )
            dtslogger.info(f"Creating local certificate for the domain '{LOCAL_DOMAIN}' and {LOCAL_IP} ...")
            cmd: List[str] = DTCommand._mkcert_command(
                "-cert-file", ssl_cert, "-key-file", ssl_key, LOCAL_DOMAIN, LOCAL_IP
            )
            dtslogger.debug(f"Running command:\n\t$ {cmd}\n\tenv: {cmd_env}\n")
            out = subprocess.check_output(cmd, env=env, stderr=STDOUT).decode("utf-8")
            print(out)
            # make sure the domain certificate was created
            if "Created a new certificate valid for the following names" not in out:
                raise Exception(f"An error occurred while creating a domain certificate:\n\n{out}")
            assert exists(ssl_cert)
            assert exists(ssl_key)
            # ---
            dtslogger.info(f"A new certificate for the domains '{LOCAL_DOMAIN}' and '{LOCAL_IP}' was created.")
        else:
            dtslogger.info(f"Existing domain certificate found in [{ssl_dir}]")
            
        # verify certificates
        DTCommand.verify_certificate_validity(ssl_cert, ca_cert)
        

    @staticmethod
    def verify_certificate_validity(domain_certificate_path: str, ca_cert_path: str):
        """Verify that the domain certificate is valid against the local Certificate Authority."""
        dtslogger.info("Verifying the domain certificate...")
        is_valid, out_verify = DTCommand.certificate_valid_for_ca(
            domain_certificate_path,
            ca_cert_path,
            log_errors=True,
        )
        dtslogger.info(f"Certificate verification result: {out_verify.strip()}")
        if not is_valid:
            raise Exception("The domain certificate is not valid.")
        dtslogger.info(f"Domain certificate is valid against CA at {ca_cert_path}!")
        dtslogger.info("If you are using a dev container, ensure the host system also trusts this root CA.")

    @staticmethod
    def certificate_valid_for_ca(
        domain_certificate_path: str,
        ca_cert_path: str,
        log_errors: bool = False,
    ):
        leaf_certificate_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as fout:
                leaf_certificate_path = fout.name
            cmd_extract: List[str] = [
                "openssl",
                "x509",
                "-in",
                domain_certificate_path,
                "-out",
                leaf_certificate_path,
            ]
            dtslogger.debug(f"Running command:\n\t$ {' '.join(str(x) for x in cmd_extract)}\n")
            subprocess.check_output(cmd_extract, stderr=STDOUT)
            cmd_verify: List[str] = [
                "openssl",
                "verify",
                "-no-CAfile",
                "-no-CApath",
                "-no-CAstore",
                "-CAfile",
                ca_cert_path,
                leaf_certificate_path,
            ]
            dtslogger.debug(f"Running command:\n\t$ {' '.join(str(x) for x in cmd_verify)}\n")
            out_verify = subprocess.check_output(cmd_verify, stderr=STDOUT).decode("utf-8")
        except subprocess.CalledProcessError as e:
            out_verify = e.output.decode("utf-8")
            if log_errors:
                dtslogger.error(
                    f"Command {' '.join(cmd_verify)} failed with exit code {e.returncode}:\n{out_verify}"
                )
            return False, out_verify
        finally:
            if leaf_certificate_path and exists(leaf_certificate_path):
                os.remove(leaf_certificate_path)
        return "OK" in out_verify, out_verify

    @staticmethod
    def _get_mkcert_bin_url() -> str:
        system = platform.system().lower()
        machine = platform.machine()
        if system not in ["darwin", "linux", "windows"]:
            raise ValueError(f"System '{system}' not supported")
        if machine not in CANONICAL_ARCH:
            raise ValueError(f"Architecture not supported '{machine}'")
        arch = {"amd64": "amd64", "arm32v7": "arm", "arm64v8": "arm64"}[CANONICAL_ARCH[machine]]
        ext = {
            "darwin": "",
            "linux": "",
            "windows": ".exe",
        }[system]
        return (
            f"https://github.com/FiloSottile/mkcert/releases/download/"
            f"v{MKCERT_VERSION}/mkcert-v{MKCERT_VERSION}-{system}-{arch}{ext}"
        )

    @staticmethod
    def _install_mkcert():
        # make bin directory
        root: str = expanduser(DTShellConstants.ROOT)
        bin_dir: str = join(root, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        # do nothing if mkcert can be found locally
        bin: str = join(bin_dir, "mkcert")
        if exists(bin):
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
        root: str = expanduser(DTShellConstants.ROOT)
        bin_dir: str = join(root, "bin")
        bin: str = join(bin_dir, "mkcert")
        assert exists(bin)
        return [bin, *args]

    @staticmethod
    def complete(shell, word, line):
        return []
