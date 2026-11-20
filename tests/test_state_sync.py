"""Regressions for the upstream property-result -> HACS notification gap.

All principals and responses are synthetic. No robot, credentials or keys.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dreame_local" / "app"))
from device import Device


class StateSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.publish = AsyncMock(return_value=1)
        self.dev = Device("100000001", "test-user", "dreame.vacuum.r2401", "cn",
                          self.publish, data_dir=Path(self.tmp.name))

    async def reply(self, result):
        await self.dev.on_message(self.dev.recv_topic,
                                  json.dumps({"id": 123, "data": {"result": result}}).encode())

    def notifications(self):
        return [(args[0], json.loads(args[1])) for args, _ in self.publish.call_args_list
                if args[0] == self.dev.status_topic]

    async def test_result_reaches_status_subscribers(self):
        self.dev.props["2.1"] = 5  # returning
        prop = {"siid": 2, "piid": 1, "value": 6, "code": 0}
        await self.reply([prop])
        self.assertEqual(self.dev.props["2.1"], 6)
        self.assertEqual(self.notifications(), [(self.dev.status_topic, {
            "data": {"method": "properties_changed", "params": [prop]}})])

    async def test_identical_server_cache_can_resync_a_stale_subscriber(self):
        self.dev.props["2.1"] = 6
        await self.reply([{"siid": 2, "piid": 1, "value": 6, "code": 0}])
        self.assertEqual(len(self.notifications()), 1)

    async def test_negative_or_unknown_result_does_not_replace_fresh_state(self):
        self.dev.props["2.1"] = 6
        for prop in ({"siid": 2, "piid": 1, "value": 5, "code": -1},
                     {"siid": 2, "piid": 1, "value": 5}):
            await self.reply([prop])
        self.assertEqual(self.dev.props["2.1"], 6)
        self.assertEqual(self.notifications(), [])

    async def test_mixed_result_preserves_only_successful_values(self):
        good = {"siid": 3, "piid": 1, "value": 100, "code": 0}
        await self.reply([good, {"siid": 2, "piid": 1, "code": -1}, "invalid"])
        self.assertTrue(self.notifications(), "Successful replies must reach subscribers")
        self.assertEqual(self.notifications()[0][1]["data"]["params"], [good])

    async def test_raw_map_result_is_not_injected_as_a_push_frame(self):
        await self.reply([{"siid": 6, "piid": 1, "value": "synthetic-map", "code": 0}])
        self.assertEqual(self.dev.props["6.1"], "synthetic-map")
        self.assertEqual(self.notifications(), [])

    async def test_action_ack_does_not_fabricate_property_notifications(self):
        await self.reply({"code": 0, "out": []})
        self.assertEqual(self.notifications(), [])

    async def test_pending_command_still_receives_its_original_result(self):
        future = asyncio.get_running_loop().create_future()
        self.dev._pending[123] = future
        result = [{"siid": 2, "piid": 1, "value": 13, "code": 0}]
        await self.reply(result)
        self.assertEqual(await future, result)
        self.assertNotIn(123, self.dev._pending)

    async def test_no_query_or_control_command_is_sent_for_resync(self):
        await self.reply([{"siid": 2, "piid": 1, "value": 13, "code": 0}])
        self.assertTrue(self.publish.call_args_list)
        self.assertTrue(all(call.args[0] == self.dev.status_topic
                            for call in self.publish.call_args_list))


if __name__ == "__main__":
    unittest.main()
