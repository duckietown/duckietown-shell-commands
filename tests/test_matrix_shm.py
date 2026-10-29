import os
import stat
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from matrix.engine.run.command import _apply_shm_path


class MatrixSharedMemoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.shm_path = os.path.join(self.directory, "world")
        self.uid = os.getuid()

    def test_private_modes_preserve_container_configuration(self):
        for mode in (0o700, 0o1700, 0o2700, 0o4700, 0o6700, 0o7700):
            directory = SimpleNamespace(
                st_mode=stat.S_IFDIR | mode,
                st_uid=self.uid,
            )
            config = {
                "command": ["--"],
                "environment": {"PYTHONUNBUFFERED": "1"},
            }
            with self.subTest(mode=mode):
                with patch.object(os, "lstat", return_value=directory):
                    _apply_shm_path(config, self.shm_path)
                self.assertEqual(config["command"], ["--"])
                self.assertEqual(
                    config["volumes"][self.directory],
                    {"bind": "/tmp/duckietown/shm", "mode": "rw"},
                )
                self.assertEqual(
                    config["environment"]["DTSHELL_SHM_PATH"],
                    "/tmp/duckietown/shm/world",
                )
                self.assertEqual(
                    config["environment"]["DT_SUPERUSER"],
                    "1" if self.uid == 0 else "0",
                )
                self.assertEqual(
                    config["environment"]["PYTHONUNBUFFERED"], "1",
                )

    def test_insecure_permissions_report_the_directory(self):
        for mode in (0o600, 0o750, 0o770, 0o755):
            directory = SimpleNamespace(
                st_mode=stat.S_IFDIR | mode,
                st_uid=self.uid,
            )
            with self.subTest(mode=mode):
                with patch.object(os, "lstat", return_value=directory):
                    with self.assertRaises(ValueError) as caught:
                        _apply_shm_path({}, self.shm_path)
                message = str(caught.exception)
                self.assertIn(self.directory, message)

    def test_foreign_ownership_reports_the_directory(self):
        directory = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o700,
            st_uid=self.uid + 1,
        )
        with patch.object(os, "lstat", return_value=directory):
            with self.assertRaises(ValueError) as caught:
                _apply_shm_path({}, self.shm_path)
        message = str(caught.exception)
        self.assertIn(self.directory, message)

    def test_symlink_directory_is_rejected(self):
        link = os.path.join(self.directory, "link")
        os.symlink(self.directory, link)
        shm_path = os.path.join(link, "world")
        with self.assertRaises(ValueError) as caught:
            _apply_shm_path({}, shm_path)
        message = str(caught.exception)
        self.assertIn(link, message)

    def test_missing_directory_is_created_with_private_permissions(self):
        directory = os.path.join(self.directory, "private")
        shm_path = os.path.join(directory, "world")
        _apply_shm_path({}, shm_path)
        created = os.lstat(directory)
        self.assertEqual(created.st_mode & 0o777, 0o700)
