"""Home-Assistant-Anbindung per MQTT-Discovery."""
from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

from device import Device, MODE, SUCTION, WATER, MODE_NAMES, SUCTION_NAMES, WATER_NAMES

log = logging.getLogger("ha")


class HaBridge:
    def __init__(self, device: Device, cfg: dict[str, Any], loop=None) -> None:
        self.dev = device
        self.loop = loop
        self.host = cfg.get("mqtt_host", "core-mosquitto")
        self.port = int(cfg.get("mqtt_port", 1883))
        self.user = cfg.get("mqtt_username") or None
        self.password = cfg.get("mqtt_password") or None
        self.base = f"dreame_local/{device.did}"
        self.name = cfg.get("device_name") or "Dreame"
        self.discovery = cfg.get("discovery_prefix", "homeassistant")
        self.client: mqtt.Client | None = None
        self.connected = False

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"dreame_local_{self.dev.did}")
        except (AttributeError, TypeError):  # paho < 2
            self.client = mqtt.Client(client_id=f"dreame_local_{self.dev.did}")
        if self.user:
            self.client.username_pw_set(self.user, self.password)
        self.client.will_set(f"{self.base}/availability", "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(2, 30)
        self.client.connect_async(self.host, self.port, keepalive=45)
        self.client.loop_start()
        log.info("MQTT-Discovery verbindet zu %s:%s", self.host, self.port)

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            try:
                self.client.disconnect()
            except Exception:
                pass

    # --------------------------------------------------------------- callbacks
    def _on_connect(self, client, userdata, flags, rc, props=None):
        if getattr(rc, "value", rc) not in (0, "Success"):
            log.warning("MQTT-Verbindung abgelehnt: %s", rc)
            return
        self.connected = True
        log.info("MQTT verbunden")
        self._discovery()
        client.publish(f"{self.base}/availability", "online", retain=True)
        for topic in (
            f"{self.base}/vacuum/command",
            f"{self.base}/select/suction/set",
            f"{self.base}/select/water/set",
            f"{self.base}/select/mode/set",
            f"{self.base}/button/+/press",
        ):
            client.subscribe(topic)
        self.publish_state()

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode(errors="replace").strip()
        topic = msg.topic
        log.info("HA-Kommando %s = %s", topic, payload)
        try:
            if topic.endswith("/vacuum/command"):
                self._vacuum_command(payload)
            elif topic.endswith("/select/suction/set"):
                self._select("SUCTION_LEVEL", payload, SUCTION_NAMES)
            elif topic.endswith("/select/water/set"):
                self._select("WATER_VOLUME", payload, WATER_NAMES)
            elif topic.endswith("/select/mode/set"):
                self._select("CLEANING_MODE", payload, MODE_NAMES)
            elif "/button/" in topic and topic.endswith("/press"):
                name = topic.split("/")[-2]
                self._button(name)
        except Exception:
            log.exception("Kommando fehlgeschlagen")

    # ---------------------------------------------------------------- commands
    def _vacuum_command(self, payload: str) -> None:
        mapping = {
            "start": ("START", None),
            "stop": ("STOP", None),
            "pause": ("PAUSE", None),
            "return_to_base": ("CHARGE", None),
            "locate": ("LOCATE", None),
        }
        if payload in mapping:
            import asyncio

            action, _ = mapping[payload]
            asyncio.run_coroutine_threadsafe(self.dev.action(action), self.loop)

    def _select(self, prop: str, payload: str, names: dict[int, str]) -> None:
        import asyncio

        rev = {v.lower(): k for k, v in names.items()}
        if payload in rev:
            asyncio.run_coroutine_threadsafe(self.dev.set_property(prop, rev[payload]), self.loop)

    def _button(self, name: str) -> None:
        import asyncio

        actions = {"locate": "LOCATE", "auto_empty": "START_AUTO_EMPTY", "wash": "START_WASHING"}
        if name in actions:
            asyncio.run_coroutine_threadsafe(self.dev.action(actions[name]), self.loop)


    # --------------------------------------------------------------- discovery
    def _device_block(self) -> dict[str, Any]:
        return {
            "identifiers": [f"dreame_local_{self.dev.did}"],
            "name": self.name,
            "manufacturer": "Dreame",
            "model": self.dev.model,
            "sw_version": self.dev.ver or "unbekannt",
        }

    def _discovery(self) -> None:
        assert self.client
        dev = self._device_block()
        uid = f"dreame_local_{self.dev.did}"

        def cfg(component: str, obj: str, payload: dict) -> None:
            payload.setdefault("device", dev)
            payload.setdefault("availability_topic", f"{self.base}/availability")
            self.client.publish(
                f"{self.discovery}/{component}/{uid}_{obj}/config",
                json.dumps(payload, ensure_ascii=False),
                retain=True,
            )

        cfg(
            "vacuum",
            "vacuum",
            {
                "unique_id": f"{uid}_vacuum",
                "schema": "state",
                "state_topic": f"{self.base}/vacuum/state",
                "command_topic": f"{self.base}/vacuum/command",
                "json_attributes_topic": f"{self.base}/vacuum/attributes",
                "battery_level_topic": f"{self.base}/sensor/battery/state",
                "battery_level_template": "{{ value }}",
                "supported_features": ["start", "stop", "pause", "return_home", "locate", "battery"],
                "payload_start": "start",
                "payload_stop": "stop",
                "payload_pause": "pause",
                "payload_return_to_base": "return_to_base",
                "payload_locate": "locate",
            },
        )

        sensors = {
            "battery": ("Batterie", "battery", "%", "battery"),
            "state_text": ("Status", "state", None, None),
            "error": ("Fehler", "error", None, None),
            "area": ("Gereinigte Fläche", "cleaned_area", "m²", None),
            "time": ("Reinigungszeit", "cleaning_time", "s", "duration"),
            "suction": ("Saugstufe", "suction", None, None),
            "water": ("Wassermenge", "water", None, None),
            "mode": ("Reinigungsmodus", "mode", None, None),
            "main_brush": ("Hauptbürste", "main_brush", "%", None),
            "side_brush": ("Seitenbürste", "side_brush", "%", None),
            "filter": ("Filter", "filter", "%", None),
            "sensor": ("Sensorreinigung", "sensor", "%", None),
            "total_area": ("Gesamtfläche", "total_area", None, None),
            "total_time": ("Gesamtzeit", "total_time", None, None),
            "total_count": ("Reinigungen", "total_count", None, None),
        }
        for obj, (name, key, unit, dclass) in sensors.items():
            p: dict[str, Any] = {
                "name": name,
                "unique_id": f"{uid}_{obj}",
                "state_topic": f"{self.base}/sensor/{obj}/state",
                "value_template": "{{ value }}",
            }
            if unit:
                p["unit_of_measurement"] = unit
            if dclass:
                p["device_class"] = dclass
            if obj == "battery":
                p["device_class"] = "battery"
            cfg("sensor", obj, p)

        for obj, name, options, topic in (
            ("suction", "Saugstufe", [v.lower() for v in SUCTION_NAMES.values() if v != "UNKNOWN"], "suction"),
            ("water", "Wassermenge", [v.lower() for v in WATER_NAMES.values() if v != "UNKNOWN"], "water"),
            ("mode", "Modus", [v.lower() for v in MODE_NAMES.values() if v != "UNKNOWN"], "mode"),
        ):
            cfg(
                "select",
                obj,
                {
                    "name": name,
                    "unique_id": f"{uid}_select_{obj}",
                    "options": options,
                    "state_topic": f"{self.base}/sensor/{topic}/state",
                    "command_topic": f"{self.base}/select/{obj}/set",
                },
            )

        for obj, name in (("locate", "Roboter finden"), ("auto_empty", "Absaugen"), ("wash", "Mopp waschen")):
            cfg(
                "button",
                obj,
                {
                    "name": name,
                    "unique_id": f"{uid}_button_{obj}",
                    "command_topic": f"{self.base}/button/{obj}/press",
                    "payload_press": "press",
                },
            )

    # ------------------------------------------------------------------- state
    def publish_state(self) -> None:
        if not (self.client and self.connected):
            return
        s = self.dev.snapshot()
        c = self.client
        # Attribute kompakt halten (kein 371-Property-Dump im Recorder)
        attrs = {k: v for k, v in s.items() if k not in ("props",)}
        attrs["props"] = {k: v for k, v in s["props"].items() if v is not None}
        c.publish(f"{self.base}/vacuum/state", s["ha_state"], retain=True)
        c.publish(f"{self.base}/vacuum/attributes", json.dumps(attrs, ensure_ascii=False), retain=True)
        values = {
            "battery": s.get("battery"),
            "state_text": s.get("state"),
            "error": s.get("error") or "kein Fehler",
            "area": s.get("cleaned_area"),
            "time": s.get("cleaning_time"),
            "suction": s.get("suction"),
            "water": s.get("water"),
            "mode": s.get("mode"),
            "main_brush": s.get("main_brush"),
            "side_brush": s.get("side_brush"),
            "filter": s.get("filter"),
            "sensor": s.get("sensor"),
            "total_area": s.get("total_area"),
            "total_time": s.get("total_time"),
            "total_count": s.get("total_count"),
        }
        for obj, value in values.items():
            c.publish(f"{self.base}/sensor/{obj}/state", "" if value is None else str(value), retain=True)
        c.publish(f"{self.base}/availability", "online" if s["online"] else "offline", retain=True)
