import argparse

from dt_shell import DTCommandAbs, dtslogger


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args, **kwargs):
        prog = "dts config docker info"
        desc = "Show info about saved docker registry credentials"
        usage = f"\n\n\t\t{prog}"

        parser = argparse.ArgumentParser(prog=prog, description=desc, usage=usage)
        _ = parser.parse_args(args)


        cred = shell.shell_config.docker_credentials

        if len(cred) == 0:
            dtslogger.warning("\n\tNo docker credentials available.\n\tPlease see how one could be configured using:\n\t\tdts config docker set --help")
        else:
            dtslogger.info(f"{len(cred)} Docker credential(s) available (format: registry | username):\n")
            for registry, credentials in cred.items():
                uname = credentials.get("username")
                dtslogger.info(f"\t- {registry:<40} | {uname}")
