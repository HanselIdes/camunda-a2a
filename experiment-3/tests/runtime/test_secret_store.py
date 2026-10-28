from pathlib import Path
import stat
import tempfile
import unittest

from isolation import write_secret_store


class SecretStorePermissionsTest(unittest.TestCase):
    def test_readable_mount_stays_inside_private_host_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = write_secret_store(root, {"A2A_API_KEY": "synthetic-test-value"})
            self.assertEqual(store.parent, root)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(store.stat().st_mode), 0o755)
            secret = store / "A2A_API_KEY"
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o444)
            self.assertEqual(secret.read_text(), "synthetic-test-value")
            self.assertFalse(root.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))
