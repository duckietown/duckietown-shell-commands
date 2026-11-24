import unittest
from unittest.mock import Mock, patch

import requests
from dt_shell import UserError
from dtps_http import CONTENT_TYPE_DTPS_DATAREADY_CBOR

from matrix.attach import command
from matrix.attach.configuration import DTCommandConfiguration


class MatrixAttachTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch.object(command.DTCommand, "parser", DTCommandConfiguration.parser()),
            patch("matrix.attach.command.KVStore", autospec=True),
            patch("matrix.attach.command.requests.post"),
        ):
            self.addCleanup(patcher.stop)
            patcher.start()
        self.kv = command.KVStore.return_value
        self.post = command.requests.post
        self.kv.get.return_value = {"robot": "test-neo", "robot_type": "duckiebot", "configuration": "DB21M"}

    def attach(self):
        command.DTCommand.command(None, [
            "--engine", "198.51.100.10", "--dreamwalk", "192.0.2.10", "environment_0/map_0/vehicle_0",
        ])

    def test_attach_reserves_with_canonical_name_even_when_addressed_by_ip(self):
        def accept(*args, **kwargs):
            self.kv.set.assert_not_called()
            return Mock(status_code=201, headers={"Content-Type": CONTENT_TYPE_DTPS_DATAREADY_CBOR})

        self.post.side_effect = accept
        self.attach()
        command.KVStore.assert_called_once_with("192.0.2.10", timeout=command.ATTACH_TIMEOUT)
        self.kv.get.assert_called_once_with(dict, "hil/identity", None)
        self.post.assert_called_once_with(
            "http://198.51.100.10:7501/hil/reserve/",
            json={
                "entity": "environment_0/map_0/vehicle_0", "robot": "test-neo",
                "robot_type": "duckiebot", "configuration": "DB21M",
            },
            timeout=command.ATTACH_TIMEOUT, allow_redirects=False,
        )
        configuration, connection = [call.args for call in self.kv.set.call_args_list]
        self.assertEqual((configuration[0], connection[0]), ("hil/configuration", "hil/connection"))
        self.assertTrue(configuration[1].dreamwalking)
        self.assertEqual(connection[1].agent_name, "environment_0/map_0/vehicle_0")
        self.assertEqual(connection[1].simulator.urls, ["http://198.51.100.10:7501/"])

    def test_rejected_target_and_unavailable_reservations_write_nothing(self):
        for status, body, reason in (
            (409, "Robot is duckiebot DB21M; entity requires duckiedrone DD24.", "duckiebot DB21M.*duckiedrone DD24"),
            (409, "Robot 'neo' is attached. Run 'dts matrix detach neo'.", "dts matrix detach neo"),
            (409, "Robot 'neo' has a pending attachment.", "pending attachment"),
            (422, "Unknown Matrix robot entity.", "Unknown Matrix"),
            (404, "Not Found", "Update the Duckiematrix Engine"),
            (201, "", "did not confirm"),
        ):
            with self.subTest(status=status, reason=reason):
                self.post.return_value = Mock(status_code=status, text=body, headers={})
                with self.assertRaisesRegex(UserError, reason):
                    self.attach()
                self.kv.set.assert_not_called()
        self.post.side_effect = requests.Timeout()
        with self.assertRaisesRegex(UserError, "Could not reserve the entity"):
            self.attach()
        self.kv.set.assert_not_called()

    def test_missing_or_invalid_robot_identity_is_not_guessed(self):
        for identity in (
            None,
            {"robot_type": "duckiebot", "configuration": "DB21J"},
            {"robot": "test-neo", "robot_type": "unknown", "configuration": "DB21J"},
        ):
            with self.subTest(identity=identity):
                self.kv.get.return_value = identity
                with self.assertRaisesRegex(UserError, r"HIL identity|valid robot type and configuration"):
                    self.attach()
                self.post.assert_not_called()
                self.kv.set.assert_not_called()
