"""Dreame-Geraeteprotokoll (Cloud-Ersatz): Zustand, Queries, Kommandos."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import events

log = logging.getLogger("device")

MAP = json.loads((Path(__file__).parent / "mapping.json").read_text())
PROPS: dict[str, dict[str, int]] = MAP["properties"]
ACTIONS: dict[str, dict[str, int]] = MAP["actions"]
STATES: dict[str, int] = MAP["state"]
ERRORS: dict[str, int] = MAP["error"]
SUCTION: dict[str, int] = MAP["suction"]
WATER: dict[str, int] = MAP["water"]
MODE: dict[str, int] = MAP["mode"]

# Rueckwaerts-Maps: Wert -> Name
def _rev(d: dict[str, int]) -> dict[int, str]:
    return {v: k for k, v in d.items()}


STATE_NAMES = _rev(STATES)
ERROR_NAMES = _rev(ERRORS)
SUCTION_NAMES = _rev(SUCTION)
WATER_NAMES = _rev(WATER)
MODE_NAMES = _rev(MODE)

HA_STATE = {
    "SWEEPING": "cleaning",
    "MOPPING": "cleaning",
    "SWEEPING_AND_MOPPING": "cleaning",
    "SECOND_CLEANING": "cleaning",
    "SPOT_CLEANING": "cleaning",
    "INITIAL_DEEP_CLEANING": "cleaning",
    "EXTRA_CLEANING": "cleaning",
    "FLOOR_MAINTAINING": "cleaning",
    "SANITIZING": "cleaning",
    "IDLE": "idle",
    "WAITING_FOR_TASK": "idle",
    "BUILDING": "idle",
    "PAUSED": "paused",
    "WASHING_PAUSED": "paused",
    "MONITORING_PAUSED": "paused",
    "ERROR": "error",
    "RETURNING": "returning",
    "RETURNING_TO_WASH": "returning",
    "RETURNING_INSTALL_MOP": "returning",
    "RETURNING_REMOVE_MOP": "returning",
    "RETURNING_AUTO_EMPTY": "returning",
    "RETURNING_TO_DRAIN": "returning",
    "CHARGING": "docked",
    "CHARGING_COMPLETED": "docked",
    "SMART_CHARGING": "docked",
    "ENTERING_DOCK": "returning",
    "LEAVING_DOCK": "cleaning",
    "UPGRADING": "idle",
}


POLL_PROPS = [
    "STATE", "ERROR", "BATTERY_LEVEL", "CHARGING_STATUS", "STATUS", "TASK_STATUS",
    "CLEANING_TIME", "CLEANED_AREA", "CLEANING_PROGRESS", "CLEANING_MODE", "CLEANING_PAUSED",
    "SUCTION_LEVEL", "WATER_VOLUME", "WATER_TANK", "DRYING_PROGRESS",
    "MAIN_BRUSH_LEFT", "MAIN_BRUSH_TIME_LEFT", "SIDE_BRUSH_LEFT", "SIDE_BRUSH_TIME_LEFT",
    "FILTER_LEFT", "FILTER_TIME_LEFT", "SENSOR_DIRTY_LEFT", "SENSOR_DIRTY_TIME_LEFT",
    "TOTAL_CLEANED_AREA", "TOTAL_CLEANING_TIME", "CLEANING_COUNT",
    "SELF_CLEAN", "CHILD_LOCK", "CARPET_BOOST", "DND", "MAP_INDEX", "MAP_NAME",
    "MOP_IN_STATION", "WATER_CHECK", "LOW_WATER_WARNING", "DRYING_TIME", "SELF_WASH_BASE_STATUS",
]


class Device:
    def __init__(
        self,
        did: str,
        uid: str,
        model: str,
        region: str,
        publish: Callable[[str, str], Awaitable[int]],
        upload_base: str = "",
        data_dir: Path | None = None,
    ) -> None:
        self.did = str(did)
        self.uid = uid
        self.model = model
        self.region = region
        self._publish = publish
        self.upload_base = upload_base.rstrip("/")
        self.data_dir = data_dir or Path("/data")
        self.props: dict[str, Any] = {}          # "siid.piid" -> value
        self.extra: dict[str, Any] = {}          # props wie ota_state
        self.info: dict[str, Any] = {}
        self.map_info: str | None = None
        self.online = False
        self.ver: str | None = None
        self._mid = int(time.time()) % 100000
        self._id = 1000
        self._pending: dict[int, asyncio.Future] = {}
        self.last_seen = 0.0
        self.listeners: list[Callable[[], Awaitable[None]]] = []
        self.firmware_log: dict[str, Any] = {}

    # ------------------------------------------------------------------ topics
    @property
    def status_topic(self) -> str:
        return f"/status/{self.did}/{self.uid}/{self.model}/{self.region}/"

    @property
    def query_topic(self) -> str:
        return f"/query/{self.did}/{self.uid}/{self.model}/{self.region}/"

    @property
    def recv_topic(self) -> str:
        return f"/recv/{self.did}/{self.uid}/{self.model}/{self.region}/"

    @property
    def ctrl_topic(self) -> str:
        return f"/ctrl/{self.did}/"

    @property
    def result_topic(self) -> str:
        return f"/result/{self.did}/"

    # ---------------------------------------------------------------- lifecycle
    async def set_online(self, online: bool) -> None:
        self.online = online
        if online:
            self.last_seen = time.time()
        await self._notify()
        if online:
            async def _delayed_poll() -> None:
                await asyncio.sleep(4)
                if self.online:
                    await self.poll_all()
            asyncio.create_task(_delayed_poll())

    async def on_message(self, topic: str, payload: bytes) -> None:
        if topic.startswith("/query/"):
            await self._handle_query(payload)
        elif topic.startswith("/status/"):
            await self._handle_status(payload)
        elif topic.startswith("/pair/"):
            await self._handle_pair(payload)
        elif topic.startswith("/recv/"):
            await self._handle_recv(payload)
        elif topic.startswith("/w/"):
            self.last_seen = time.time()

    async def _handle_pair(self, payload: bytes) -> None:
        try:
            data = json.loads(payload).get("data", {})
        except Exception:
            return
        if data.get("method") == "dev_start":
            p = data.get("params", {})
            self.ver = p.get("ver") or self.ver
            if p.get("uid"):
                self.uid = str(p["uid"])
            if p.get("model"):
                self.model = str(p["model"])
            if p.get("did"):
                self.did = str(p["did"])
            log.info("dev_start: ver=%s uid=%s model=%s domain=%s", p.get("ver"), p.get("uid"), p.get("model"), p.get("domain"))
            # Die Cloud antwortet mit einem leeren Ergebnis.
            try:
                mid = json.loads(payload).get("id", 0)
            except Exception:
                mid = 0
            await self._publish(self.result_topic, json.dumps({"id": mid}))
            await self.poll_all()

    async def _handle_status(self, payload: bytes) -> None:
        self.last_seen = time.time()
        try:
            data = json.loads(payload).get("data", {})
        except Exception:
            return
        method = data.get("method")
        params = data.get("params")
        changed = False
        if method == "properties_changed" and isinstance(params, list):
            for p in params:
                try:
                    key = f"{p['siid']}.{p['piid']}"
                except Exception:
                    continue
                if self.props.get(key) != p.get("value"):
                    self.props[key] = p.get("value")
                    changed = True
        elif method == "props" and isinstance(params, dict):
            self.extra.update(params)
            changed = True
        elif method == "_otc.info" and isinstance(params, dict):
            self.info = params
            self.ver = (params.get("params") or {}).get("fw_ver") or self.ver
            changed = True
        elif method == "_sync.update_vacuum_mapinfo" and isinstance(params, dict):
            self.map_info = params.get("map_info")
            changed = True
        elif method is not None and isinstance(params, dict):
            self.extra[method] = params
            changed = True
        if changed:
            await self._notify()

    async def _handle_recv(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
        except Exception:
            return
        rid = msg.get("id")
        if rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                fut.set_result(msg.get("data", {}).get("result"))
            events.add("command_result", id=rid)
        data = msg.get("data", {})
        result = data.get("result")
        # get_properties liefert [{siid,piid,value,code}] -> direkt in den Zustand
        changed = False
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and "siid" in item and "piid" in item and "value" in item:
                    key = f"{item['siid']}.{item['piid']}"
                    if self.props.get(key) != item["value"]:
                        self.props[key] = item["value"]
                        changed = True
        if changed:
            await self._notify()
        if isinstance(result, dict) and "code" in result:
            log.debug("Ergebnis %s: %s", rid, result)

    async def _handle_query(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
        except Exception:
            return
        data = msg.get("data") or {}
        method = data.get("method")
        mid = msg.get("id", data.get("id", 0))
        params = data.get("params") or {}

        if method == "local.query_time":
            await self._publish(
                self.result_topic, json.dumps({"id": mid, "method": "local.time", "params": int(time.time())})
            )
            return

        if method and str(method).startswith("_sync."):
            log.info("Sync-Anfrage: %s %s", method, params)
            events.add("sync_request", method=method, params=params)
        if method == "_sync.gen_presigned_url" and isinstance(params, dict):
            suffix = params.get("suffix") or "upload.bin"
            entry = self._upload_entry(
                self._pack_name(suffix), prefix="device-log/pack/000000"
            )
            log.info("Upload-URL (Log): %s", entry.get("url"))
            await self._publish(self.result_topic, json.dumps({"id": mid, "result": {suffix: entry}}))
            return

        if method == "_sync.gen_tmp_presigned_url" and isinstance(params, dict):
            idx = params.get("indexes") or []
            urls = []
            for i in idx:
                name = f"ali_dreame/{self.uid}/{self.did}/{i}"
                urls.append(self._upload_entry(name, index=i))
            if not self.upload_base:
                log.warning(
                    "Presigned-URL angefragt, aber lan_ip/upload_port fehlen – "
                    "der Roboter kann die Karte nicht hochladen"
                )
            elif urls:
                log.info("Upload-URLs erzeugt: %d, z.B. %s", len(urls), urls[0].get("url"))
            events.add("presigned_urls", indexes=idx, base=self.upload_base)
            await self._publish(self.result_topic, json.dumps({"id": mid, "result": {"urls": urls}}))
            return

        log.debug("Query unbeantwortet: %s %s", method, params)

    def _upload_entry(
        self, name: str, index: int | None = None, prefix: str = "iot/tmp/000000"
    ) -> dict[str, Any]:
        """Antwortobjekt wie in der echten Cloud.

        Wichtig: Der Roboter ordnet die Upload-URLs ueber das Feld ``index``
        den Kartendateien zu. Fehlt es, werden die URLs verworfen und es
        kommt nie ein Upload zustande.
        """
        if not self.upload_base:
            return {"ok": False, "obj_name": name}
        expires = int(time.time()) + 3600
        # Query-Parameter wie bei einer echten OSS-Presigned-URL. Der Roboter
        # bzw. das OSS-SDK wertet sie ggf. aus; unser Upload-Server ignoriert
        # sie einfach.
        query = (
            f"Expires={expires}"
            f"&OSSAccessKeyId=local"
            f"&Signature=local"
        )
        entry: dict[str, Any] = {
            # Gleiche Pfadform wie die echte OSS-URL:
            # https://dreame-eu.iot.dreame.tech/<prefix>/ali_dreame/...
            "url": f"{self.upload_base}/{prefix}/{name}?{query}",
            "method": "PUT",
            "ok": True,
            "obj_name": name,
            "expires_time": expires,
            "pwd": secrets.token_urlsafe(16),
        }
        if index is not None:
            entry["index"] = int(index)
        return entry

    def _pack_name(self, suffix: str) -> str:
        now = time.localtime()
        return (
            f"ali_dreame/{now.tm_year}/{now.tm_mon:02d}/{now.tm_mday:02d}/{self.uid}/"
            f"{self.did}_{now.tm_hour:02d}{now.tm_min:02d}{now.tm_sec:02d}.{suffix}"
        )

    # ----------------------------------------------------------------- commands
    async def send(self, method: str, params: Any, timeout: float = 8.0) -> Any:
        self._mid += 1
        rid = self._id = self._id + 1
        body = {
            "mid": self._mid,
            "did": self.did,
            "id": rid,
            "method": method,
            "from": "userIot",
            "params": params,
        }
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        log.info("-> %s", method)
        events.add("command", method=method)
        if not await self._publish(self.ctrl_topic, json.dumps(body)):
            self._pending.pop(rid, None)
            raise RuntimeError("Roboter nicht verbunden")
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise TimeoutError(f"Keine Antwort auf {method}")

    async def action(self, name: str, value: Any = None, piid: int | None = None) -> Any:
        a = ACTIONS.get(str(name).upper())
        if not a:
            raise ValueError(f"Unbekannte Action {name}")
        params: dict[str, Any] = {"did": self.did, "siid": a["siid"], "aiid": a["aiid"]}
        params["in"] = [] if piid is None else [{"piid": piid, "value": value}]
        return await self.send("action", params)

    async def set_property(self, prop: str, value: Any) -> Any:
        p = PROPS.get(prop)
        if not p:
            raise ValueError(f"Unbekannte Property {prop}")
        return await self.send(
            "set_properties", [{"did": self.did, "siid": p["siid"], "piid": p["piid"], "value": value}]
        )

    async def raw_action(self, siid: int, aiid: int, in_params: list[dict] | None = None) -> Any:
        params = {"did": self.did, "siid": siid, "aiid": aiid, "in": in_params or []}
        return await self.send("action", params)

    async def get_properties(self, names: list[str]) -> Any:
        items = []
        for n in names:
            p = PROPS.get(n)
            if p:
                items.append({"did": self.did, "siid": p["siid"], "piid": p["piid"]})
        return await self.send("get_properties", items)

    async def poll_all(self) -> None:
        """Relevante Properties in kleinen Bloecken abfragen."""
        for i in range(0, len(POLL_PROPS), 12):
            try:
                await self.get_properties(POLL_PROPS[i : i + 12])
            except Exception as exc:  # pragma: no cover
                log.debug("Abfrageblock %d fehlgeschlagen: %s", i, exc)
                break

    # -------------------------------------------------------------- state view
    def get(self, prop: str, default: Any = None) -> Any:
        p = PROPS.get(prop)
        if not p:
            return default
        return self.props.get(f"{p['siid']}.{p['piid']}", default)

    def snapshot(self) -> dict[str, Any]:
        named = {name: self.get(name) for name in PROPS}
        state_code = self.get("STATE")
        error_code = self.get("ERROR")
        state_name = STATE_NAMES.get(state_code, "UNKNOWN") if state_code is not None else "UNKNOWN"
        return {
            "did": self.did,
            "uid": self.uid,
            "model": self.model,
            "region": self.region,
            "online": self.online,
            "ver": self.ver,
            "state_code": state_code,
            "state": state_name,
            "ha_state": HA_STATE.get(state_name, "idle"),
            "error_code": error_code,
            "error": ERROR_NAMES.get(error_code) if error_code else None,
            "battery": self.get("BATTERY_LEVEL"),
            "charging": self.get("CHARGING_STATUS"),
            "cleaned_area": self.get("CLEANED_AREA"),
            "cleaning_time": self.get("CLEANING_TIME"),
            "suction": (SUCTION_NAMES.get(self.get("SUCTION_LEVEL")) or "").lower() or None,
            "water": (WATER_NAMES.get(self.get("WATER_VOLUME")) or "").lower() or None,
            "mode": (MODE_NAMES.get(self.get("CLEANING_MODE")) or "").lower() or None,
            "main_brush": self.get("MAIN_BRUSH_LEFT"),
            "side_brush": self.get("SIDE_BRUSH_LEFT"),
            "filter": self.get("FILTER_LEFT"),
            "sensor": self.get("SENSOR_DIRTY_LEFT"),
            "total_area": self.get("TOTAL_CLEANED_AREA"),
            "total_time": self.get("TOTAL_CLEANING_TIME"),
            "total_count": self.get("CLEANING_COUNT"),
            "ota_state": self.extra.get("ota_state"),
            "props": named,
            "info": self.info,
        }

    async def _notify(self) -> None:
        for cb in self.listeners:
            try:
                await cb()
            except Exception:  # pragma: no cover
                log.exception("Listener-Fehler")
