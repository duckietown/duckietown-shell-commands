import argparse
from typing import Optional

from dt_shell.commands import DTCommandConfigurationAbs

from devel.template.diff.configuration import DTCommandConfiguration as DevelTemplateDiffCommandConfiguration


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        return DevelTemplateDiffCommandConfiguration.parser(*args, **kwargs)
