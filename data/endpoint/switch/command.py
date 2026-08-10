import questionary
from questionary import Choice

from dt_shell import DTCommandAbs, UserAborted, dtslogger
from dt_shell.utils import cli_style

from utils.data_endpoint_utils import (
    STORAGE_ENDPOINTS,
    get_storage_endpoint,
    set_storage_endpoint,
)


class DTCommand(DTCommandAbs):
    help = "Switches the S3 endpoint used by a storage space"

    @staticmethod
    def command(shell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        current_endpoint = get_storage_endpoint(shell, parsed.space)
        selected_endpoint = parsed.endpoint

        if selected_endpoint is None:
            choices = []
            for endpoint in STORAGE_ENDPOINTS:
                suffix = " (current)" if endpoint == current_endpoint else ""
                choices.append(
                    Choice(
                        title=[
                            ("class:choice", endpoint),
                            ("class:disabled", suffix),
                        ],
                        value=endpoint,
                    )
                )
            selected_endpoint = questionary.select(
                f"Choose the '{parsed.space}' storage S3 endpoint:",
                choices=choices,
                style=cli_style,
            ).unsafe_ask()
            if selected_endpoint is None:
                raise UserAborted()

        if selected_endpoint == current_endpoint:
            dtslogger.info(
                f"Already using the '{selected_endpoint}' endpoint for the "
                f"'{parsed.space}' storage space."
            )
            return

        set_storage_endpoint(shell, parsed.space, selected_endpoint)
        dtslogger.info(
            f"The '{parsed.space}' storage endpoint is now set to '{selected_endpoint}'."
        )
