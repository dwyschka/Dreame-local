"""Read-only map parsing fixtures, without robot identity or real map data."""
import base64
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dreame_local" / "app"))
Web = importlib.import_module("web").Web


def blob():
    raw = bytearray(27)
    raw[19:21] = (4).to_bytes(2, "little")
    raw[21:23] = (3).to_bytes(2, "little")
    raw += bytes(range(12))
    raw += json.dumps({"timestamp_ms": 1000, "seg_inf": {}}).encode()
    return base64.b64encode(zlib.compress(raw)).decode()


class WebMapTests(unittest.TestCase):
    def load_saved(self, root, uid="", did="synthetic-device"):
        return Web(SimpleNamespace(uid=uid, did=did, props={}), data_dir=root)._load_map()

    def save_map(self, root, uid, did="synthetic-device"):
        path = root / "uploads" / "ali_dreame" / uid / did / "9"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mapstr": [{"map": blob()}]}))

    def test_missing_uid_uses_only_unique_same_device_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.save_map(root, "synthetic-account")
            self.assertIsNotNone(self.load_saved(root))

    def test_missing_uid_never_selects_other_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.save_map(root, "synthetic-account", did="different-device")
            self.assertIsNone(self.load_saved(root))

    def test_missing_uid_rejects_ambiguous_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.save_map(root, "synthetic-account-a")
            self.save_map(root, "synthetic-account-b")
            self.assertIsNone(self.load_saved(root))

    def test_known_uid_never_falls_back_to_other_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.save_map(root, "different-account")
            self.assertIsNone(self.load_saved(root, uid="known-account"))

    def test_existing_raw_frame(self):
        decoded = Web._decode_map_text(blob())
        self.assertEqual(decoded[1:3], (4, 3))
        self.assertEqual(decoded[0][27:39], bytes(range(12)))

    def test_map_list_wrapper_matches_raw_frame(self):
        self.assertEqual(Web._decode_map_text(json.dumps({"mapstr": [{"map": blob()}]})),
                         Web._decode_map_text(blob()))

    def test_wrapper_skips_invalid_candidate(self):
        wrapped = {"mapstr": [None, {"map": "broken"}, {"map": blob()}]}
        self.assertEqual(Web._decode_map_text(json.dumps(wrapped)), Web._decode_map_text(blob()))

    def test_invalid_wrappers_fail_closed(self):
        for text in ("{", "{}", '{"mapstr":null}', '{"mapstr":"invalid"}',
                     '{"mapstr":[{"map":null}]}', '{"mapstr":[{"map":"{}"}]}'):
            with self.subTest(text=text):
                self.assertIsNone(Web._decode_map_text(text))

    def test_empty_and_truncated_frame_fail_closed(self):
        for text in ("", "not a frame", base64.b64encode(zlib.compress(b"short")).decode()):
            with self.subTest(text=text):
                self.assertIsNone(Web._decode_map_text(text))

    def test_existing_urlsafe_and_frame_suffix(self):
        for text in (blob().replace("/", "_").replace("+", "-").rstrip("="), blob() + ",synthetic"):
            with self.subTest(text=text):
                self.assertEqual(Web._decode_map_text(text), Web._decode_map_text(blob()))


if __name__ == "__main__":
    unittest.main()
