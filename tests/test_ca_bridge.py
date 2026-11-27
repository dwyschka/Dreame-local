"""CA-Bridge: CA finden, certifi patchen, Integrations-Cache zuruecksetzen."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CA_PY = ROOT / "dreame_local" / "app" / "dreame_local_ca" / "ca.py"
spec = importlib.util.spec_from_file_location("dreame_local_ca_ca", CA_PY)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)  # type: ignore[union-attr]
find_ca = module.find_ca
install_ca = module.install_ca
reset_dreame_store = module.reset_dreame_store

CA = b"""-----BEGIN CERTIFICATE-----
MIIB
-----END CERTIFICATE-----"""


class FindCaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_skips_missing_and_invalid(self):
        (self.root / "bad.pem").write_text("kein zertifikat")
        (self.root / "ca.pem").write_bytes(CA + b"\n")
        self.assertEqual(find_ca((self.root / "missing.pem", self.root / "bad.pem", self.root / "ca.pem")), CA)

    def test_none_when_empty(self):
        self.assertIsNone(find_ca((self.root / "missing.pem",)))


class InstallCaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "cacert.pem"
        self.target.write_bytes(b"root1\nroot2\n")

    def test_appends_once_and_creates_backup(self):
        self.assertTrue(install_ca(CA, self.target))
        self.assertIn(CA, self.target.read_bytes())
        self.assertEqual((Path(str(self.target) + ".bak")).read_bytes(), b"root1\nroot2\n")
        self.assertFalse(install_ca(CA, self.target))

    def test_without_ca_does_nothing(self):
        before = self.target.read_bytes()
        self.assertFalse(install_ca(b"", self.target))
        self.assertEqual(self.target.read_bytes(), before)


class ResetStoreTests(unittest.TestCase):
    def tearDown(self):
        for name in (
            "custom_components.dreame_vacuum.dreame.protocol",
            "dreame_vacuum.dreame.protocol",
        ):
            sys.modules.pop(name, None)

    def test_resets_cached_store(self):
        class Socket:
            _store = object()

        class Protocol:
            DreameTLSSocket = Socket

        module = types.ModuleType("custom_components.dreame_vacuum.dreame.protocol")
        module.DreameVacuumDreameHomeCloudProtocol = Protocol
        sys.modules[module.__name__] = module

        self.assertTrue(reset_dreame_store())
        self.assertIsNone(Socket._store)
        self.assertFalse(reset_dreame_store())

    def test_missing_module_is_noop(self):
        self.assertFalse(reset_dreame_store())


if __name__ == "__main__":
    unittest.main()
