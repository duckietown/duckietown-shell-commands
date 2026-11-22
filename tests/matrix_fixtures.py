import unittest
from unittest.mock import Mock

from matrix.run.configuration import DTCommandConfiguration as MatrixConfiguration


class RendererLaunchFixture(unittest.TestCase):
    def setUp(self):
        self.parser = MatrixConfiguration.parser()
        self.shell = Mock()
        self.shell.profile.secrets.dt_token = "unit-test-placeholder"
        self.shell.get_billboard_names.return_value = []
