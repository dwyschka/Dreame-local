"""Web regression cases independent of X40; all device sends are intercepted."""
import importlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dreame_local" / "app"))
Device = importlib.import_module("device").Device
PROPS = importlib.import_module("device").PROPS
Web = importlib.import_module("web").Web


class CommonWebControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = Device("SYNTHETIC_DID", "SYNTHETIC_UID", "synthetic-legacy-model", "eu", AsyncMock(), data_dir=Path(self.tmp.name))
        self.dev.send = AsyncMock(return_value={"code": 0})
        self.dev.ensure_saved_map = AsyncMock()
        for prop, value in (("SUCTION_LEVEL", 0), ("WATER_VOLUME", 2)):
            p = PROPS[prop]
            self.dev.props[f"{p['siid']}.{p['piid']}"] = value
        self.web = Web(self.dev, data_dir=Path(self.tmp.name))
        self.web._load_map = Mock(return_value={"map_id": 24})

    async def post(self, path, body):
        async with TestClient(TestServer(self.web.app)) as client:
            response = await client.post(path, json=body)
            return response.status, await response.json()

    async def test_ui_return_identifier_resolves_to_charge(self):
        status, body = await self.post("/api/command", {"action": "return_to_base"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        method, params = self.dev.send.await_args.args
        self.assertEqual(method, "action")
        actions = importlib.import_module("device").ACTIONS
        self.assertEqual((params["siid"], params["aiid"]), (actions["CHARGE"]["siid"], actions["CHARGE"]["aiid"]))

    async def test_room_clean_preserves_valid_quiet_zero(self):
        _, body = await self.post("/api/rooms/action", {"action": "clean", "ids": [1]})
        self.assertTrue(body["ok"])
        params = self.dev.send.await_args.args[1]
        payload = json.loads(next(p["value"] for p in params["in"] if p["piid"] == 10))
        self.assertEqual(payload["selects"][0][2], 0)

    async def test_rejected_robot_action_is_not_reported_as_success(self):
        self.dev.send.return_value = {"code": -1}
        _, body = await self.post("/api/command", {"action": "stop"})
        self.assertFalse(body["ok"])
        self.assertIn("error", body)

    async def test_rejected_property_in_list_is_not_reported_as_success(self):
        self.dev.send.return_value = [{"code": 0}, {"code": -2}]
        _, body = await self.post("/api/command", {"set": "SUCTION_LEVEL", "value": 0})
        self.assertFalse(body["ok"])
        self.assertEqual(body["result"], [{"code": 0}, {"code": -2}])

    async def test_successful_action_and_property_results_remain_successful(self):
        for result in ({"code": 0}, [{"code": 0}]):
            self.dev.send.return_value = result
            _, body = await self.post("/api/command", {"action": "stop"})
            self.assertTrue(body["ok"])
            self.assertEqual(body["result"], result)

    async def test_missing_fan_keeps_existing_default(self):
        p = PROPS["SUCTION_LEVEL"]
        self.dev.props.pop(f"{p['siid']}.{p['piid']}")
        _, body = await self.post("/api/rooms/action", {"action": "clean", "ids": [1]})
        self.assertTrue(body["ok"])
        params = self.dev.send.await_args.args[1]
        payload = json.loads(next(p["value"] for p in params["in"] if p["piid"] == 10))
        self.assertEqual(payload["selects"][0][2], 2)

    def test_cleaning_time_label_is_minutes(self):
        page = importlib.import_module("web").PAGE
        self.assertIn("s.cleaning_time+' min'", page)
        self.assertNotIn("s.cleaning_time+' s'", page)



if __name__ == "__main__":
    unittest.main()
