"""Dreame Local CA Bridge.

Traegt die CA des Add-ons in certifi ein, setzt den TLS-Cache der
Dreame-Vacuum-Integration zurueck und laedt deren Eintraege neu. Damit
ueberlebt der Trust HA-Core-Updates, ohne dass das Installationsskript
erneut laufen muss.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant

from .ca import find_ca, install_ca, reset_dreame_store
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_RETRY_INTERVAL = 30
_RETRIES = 20


async def _apply(hass: HomeAssistant) -> bool:
    try:
        changed = await hass.async_add_executor_job(install_ca)
    except Exception as exc:  # pragma: no cover - abhaengig vom Container
        _LOGGER.error("CA konnte nicht in certifi eingetragen werden: %s", exc)
        changed = False
    try:
        reset = await hass.async_add_executor_job(reset_dreame_store)
    except Exception:
        reset = False
    if changed:
        _LOGGER.info("Dreame-Local-CA in certifi eingetragen")
    if reset:
        _LOGGER.info("TLS-Store-Cache der Dreame-Vacuum-Integration zurueckgesetzt")
    return changed or reset


async def _reload_dreame(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries("dreame_vacuum"):
        try:
            await hass.config_entries.async_reload(entry.entry_id)
        except Exception as exc:  # pragma: no cover - Integration nicht geladen
            _LOGGER.warning("Dreame-Vacuum-Eintrag %s nicht neu geladen: %s", entry.entry_id, exc)


async def _wait_for_ca(hass: HomeAssistant) -> None:
    """Wartet auf den CA-Export, falls HA vor dem Add-on startet."""
    for _ in range(_RETRIES):
        await asyncio.sleep(_RETRY_INTERVAL)
        if find_ca() is not None:
            if await _apply(hass):
                await _reload_dreame(hass)
            return
    _LOGGER.warning(
        "Keine Dreame-Local-CA unter /share oder /config gefunden – "
        "Add-on einmal starten und HA Core neu starten"
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    needs_reload = await _apply(hass)
    if needs_reload:
        async def _reload_after_start(_event) -> None:
            await _reload_dreame(hass)

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _reload_after_start)

    if find_ca() is None:
        hass.async_create_task(_wait_for_ca(hass))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
