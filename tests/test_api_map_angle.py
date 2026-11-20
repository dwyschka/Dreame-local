"""Signed map-angle regression; synthetic frames only, no device connection."""
import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dreame_local" / "app"))
from api import DreameApi


def frame(angle, *, frame_id=1, x=100, y=-50):
    raw = bytearray(27)
    raw[0:2] = (1).to_bytes(2, "little")
    raw[2:4] = frame_id.to_bytes(2, "little")
    raw[5:7] = x.to_bytes(2, "little", signed=True)
    raw[7:9] = y.to_bytes(2, "little", signed=True)
    raw[9:11] = angle.to_bytes(2, "little", signed=True)
    raw[19:21] = (4).to_bytes(2, "little")
    raw[21:23] = (3).to_bytes(2, "little")
    raw += bytes([1] * 12)
    raw += json.dumps({"timestamp_ms": 1000}).encode()
    return base64.b64encode(zlib.compress(raw)).decode()


def decode(blob):
    return zlib.decompress(base64.b64decode(blob))


class MapAngleTests(unittest.TestCase):
    def api(self, live):
        api = DreameApi.__new__(DreameApi)
        api.dev = SimpleNamespace(props={"6.1": live} if live else {}, map_path="")
        return api

    def test_signed_angle_and_large_positive_preserve_both_bytes(self):
        for angle in (-32768, -360, -180, -30, -1, 0, 90, 255, 256, 300, 359, 32767):
            with self.subTest(angle=angle):
                live = frame(angle, frame_id=12, x=-120, y=250)
                raw = decode(self.api(live)._as_current_map(frame(45)))
                self.assertEqual(raw[9:11], decode(live)[9:11])
                self.assertEqual(int.from_bytes(raw[9:11], "little", signed=True), angle)

    def test_positive_live_angle_clears_negative_saved_high_byte(self):
        raw = decode(self.api(frame(90))._as_current_map(frame(-90)))
        self.assertEqual(int.from_bytes(raw[9:11], "little", signed=True), 90)

    def test_position_frame_id_and_saved_map_dimensions_are_preserved(self):
        live, saved = frame(300, frame_id=12, x=-120, y=250), frame(-90)
        raw = decode(self.api(live)._as_current_map(saved))
        self.assertEqual(raw[0:2], decode(saved)[0:2])
        self.assertEqual(raw[2:9], decode(live)[2:9])
        self.assertEqual(raw[19:23], decode(saved)[19:23])
        self.assertEqual(json.loads(raw[39:])["fsm"], 1)

    def test_saved_angle_remains_when_live_frame_is_absent(self):
        raw = decode(self.api(None)._as_current_map(frame(-90)))
        self.assertEqual(int.from_bytes(raw[9:11], "little", signed=True), -90)

    def test_truncated_live_header_does_not_overwrite_saved_angle(self):
        live = base64.b64encode(zlib.compress(bytes(10))).decode()
        raw = decode(self.api(live)._as_current_map(frame(-90)))
        self.assertEqual(int.from_bytes(raw[9:11], "little", signed=True), -90)

    def test_bad_saved_map_falls_back_unchanged(self):
        self.assertEqual(self.api(frame(300))._as_current_map("not-a-map"), "not-a-map")


if __name__ == "__main__":
    unittest.main()
