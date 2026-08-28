import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger

from .. import _implementation as sd_card_impl
from utils.exceptions import InvalidUserInput
from utils.host_runner import HostRunnerError, delegate_sd_card_update_to_host


class DTCommand(DTCommandAbs):
    help = "Update selected settings on an initialized SD card"

    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--type",
            dest="robot_type",
            choices=sd_card_impl.get_robot_types(),
            required=True,
            help="Existing robot type, used to identify the card layout",
        )
        parser.add_argument(
            "--configuration",
            dest="robot_configuration",
            required=True,
            help="Existing robot configuration, used to identify the card layout",
        )
        parser.add_argument("--device", default=None, help="The SD card device to update")
        parser.add_argument("--hostname", default=None, help="New hostname for the device")
        parser.add_argument("--wifi", default=None, help="Replacement WiFi network list")
        parser.add_argument("--country", default=None, help="Replacement 2-letter WiFi country code")
        parser.add_argument(
            "--experimental",
            default=False,
            action="store_true",
            help="Use the experimental disk image layout",
        )
        parser.add_argument(
            "-S",
            "--size",
            default=None,
            type=int,
            help="Optional SD card size used when selecting a device",
        )
        parser.add_argument(
            "--workdir",
            default=sd_card_impl.TMP_WORKDIR,
            help="Directory containing cached disk image metadata",
        )
        parser.add_argument(
            "--version",
            dest="disk_image_version",
            default=None,
            help="Override the expected disk image version",
        )
        parser.add_argument(
            "--placeholders-version",
            dest="placeholders_version",
            default=None,
            help="Override the expected placeholder format version",
        )
        parser.add_argument(
            "--local",
            default=False,
            action="store_true",
            help="Run locally instead of delegating the update to the host",
        )
        parser.add_argument(
            "--repair",
            default=False,
            action="store_true",
            help="Attempt an automatic ext4 repair if preflight detects a problem",
        )
        parsed = parser.parse_args(args=args)

        if all(value is None for value in (parsed.hostname, parsed.wifi, parsed.country)):
            parser.error("Specify at least one setting to update: --hostname, --wifi, or --country.")

        if sd_card_impl._should_delegate_sd_card(parsed):
            dtslogger.info("Delegating SD card update to the host...")
            try:
                exit_code = delegate_sd_card_update_to_host(args)
            except HostRunnerError as error:
                parser.error(str(error))
            if exit_code != 0:
                exit(exit_code)
            return

        try:
            sd_card_impl.update_sd_card(shell, parsed)
        except InvalidUserInput as error:
            parser.error(str(error))
