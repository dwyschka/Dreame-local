"""certutil: resolve_material (Fallback/Pfad/inline-PEM) und ensure_api_cert (lokale CA + SAN-Leaf)."""
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dreame_local" / "app"))
from certutil import ensure_api_cert, export_ca, resolve_material


class ResolveMaterialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)

    def test_empty_uses_fallback(self):
        self.assertEqual(resolve_material("", "/fallback.pem", self.data_dir, "x.pem"), "/fallback.pem")
        self.assertEqual(resolve_material("   ", "/fallback.pem", self.data_dir, "x.pem"), "/fallback.pem")
        self.assertEqual(resolve_material(None, "/fallback.pem", self.data_dir, "x.pem"), "/fallback.pem")  # type: ignore[arg-type]

    def test_path_passthrough(self):
        self.assertEqual(
            resolve_material("/data/certs/api_chain.pem", "/fallback.pem", self.data_dir, "x.pem"),
            "/data/certs/api_chain.pem",
        )

    def test_inline_pem_is_materialized(self):
        pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"
        out = resolve_material(pem, "/fallback.pem", self.data_dir, "api_chain.pem")
        self.assertEqual(out, str(self.data_dir / "generated" / "api_chain.pem"))
        self.assertIn("-----BEGIN CERTIFICATE-----", Path(out).read_text())


class EnsureApiCertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)

    def _load(self, path):
        return x509.load_pem_x509_certificate(Path(path).read_bytes())

    def test_generates_valid_chain_with_san(self):
        chain, key, ca = ensure_api_cert(self.data_dir, "eu")
        leaf = self._load(self.data_dir / "certs" / "api.pem")
        ca_cert = self._load(ca)
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertIn("eu.iot.dreame.tech", san.get_values_for_type(x509.DNSName))
        self.assertIn("*.iot.dreame.tech", san.get_values_for_type(x509.DNSName))
        self.assertEqual(leaf.issuer, ca_cert.subject)
        self.assertTrue(
            ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
        )
        self.assertTrue(
            leaf.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
        )
        self.assertTrue(
            leaf.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
        )
        ca_cert.public_key().verify(
            leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm)
        )
        self.assertTrue(Path(key).is_file())
        self.assertTrue(Path(chain).read_bytes().endswith(Path(ca).read_bytes()))

    def test_region_in_san(self):
        ensure_api_cert(self.data_dir, "us")
        leaf = self._load(self.data_dir / "certs" / "api.pem")
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertIn("us.iot.dreame.tech", san.get_values_for_type(x509.DNSName))

    def test_idempotent(self):
        chain1, _, _ = ensure_api_cert(self.data_dir, "eu")
        serial1 = self._load(self.data_dir / "certs" / "api.pem").serial_number
        chain2, _, _ = ensure_api_cert(self.data_dir, "eu")
        self.assertEqual(chain1, chain2)
        self.assertEqual(serial1, self._load(self.data_dir / "certs" / "api.pem").serial_number)

    def test_export_ca_to_existing_directories_only(self):
        _, _, ca = ensure_api_cert(self.data_dir, "eu")
        share = self.data_dir / "share"
        share.mkdir()
        missing = self.data_dir / "missing"
        written = export_ca(self.data_dir, share, missing)

        self.assertEqual(written, [str(share / "dreame-local-ca.pem")])
        self.assertEqual((share / "dreame-local-ca.pem").read_bytes(), Path(ca).read_bytes())
        self.assertFalse(missing.exists())

    def test_export_ca_without_generated_ca(self):
        share = self.data_dir / "share"
        share.mkdir()
        self.assertEqual(export_ca(self.data_dir, share), [])


if __name__ == "__main__":
    unittest.main()
