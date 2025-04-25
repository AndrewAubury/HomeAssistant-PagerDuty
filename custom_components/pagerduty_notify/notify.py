"""Notify entity that sends events to PagerDuty (Events API v2)."""
from __future__ import annotations

import logging
from typing import Final

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.components.notify import CONF_NAME, NotifyEntity
from homeassistant.const import CONF_PLATFORM
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

CONF_ROUTING_KEY: Final = "routing_key"
CONF_DEFAULT_SOURCE: Final = "default_source"
CONF_DEFAULT_SEVERITY: Final = "default_severity"

EVENTS_API_URL: Final = "https://events.pagerduty.com/v2/enqueue"
HTTP_TIMEOUT: Final = 10

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ROUTING_KEY): cv.string,
        vol.Optional(CONF_DEFAULT_SOURCE, default="home-assistant"): cv.string,
        vol.Optional(CONF_DEFAULT_SEVERITY, default="info"): cv.string,
        vol.Optional(CONF_NAME, default="pagerduty"): cv.string,
    }
)


async def async_get_service(
    hass: HomeAssistant, config: ConfigType, discovery_info=None
):  # pylint: disable=unused-argument
    """Set up the PagerDuty notify entity."""
    return PagerDutyNotifyEntity(
        name=config[CONF_NAME],
        routing_key=config[CONF_ROUTING_KEY],
        default_source=config[CONF_DEFAULT_SOURCE],
        default_severity=config[CONF_DEFAULT_SEVERITY],
    )


class PagerDutyNotifyEntity(NotifyEntity):
    """Home Assistant notification entity that delivers to PagerDuty."""

    _attr_has_entity_name = True

    def __init__(self, name, routing_key, default_source, default_severity):
        self._attr_name = name
        self._routing_key = routing_key
        self._source = default_source
        self._severity = default_severity
        self._session: aiohttp.ClientSession | None = None

    # ----------  Home Assistant hooks  ----------
    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Trigger (or update) an incident in PagerDuty."""
        if self._session is None:  # lazy-create to avoid startup overhead
            self._session = aiohttp.ClientSession()

        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": title or message,
                "source": self._source,
                "severity": self._severity,
            },
        }

        # Allow advanced users to override PagerDuty fields via Jinja-templates:
        #   service: notify.send_message
        #   data:
        #     entity_id: notify.pagerduty
        #     message: '{{ state_attr("sensor.my_pi","last_message") }}'
        #     title: 'High temperature'
        #
        # If you need dedup_key, component, etc., add them via
        # a second call to self.notify (see README).

        try:
            async with async_timeout.timeout(HTTP_TIMEOUT):
                async with self._session.post(
                    EVENTS_API_URL, json=payload
                ) as response:
                    if response.status != 202:
                        body = await response.text()
                        _LOGGER.error(
                            "PagerDuty response %s: %s", response.status, body
                        )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Failed to send PagerDuty event")

    async def async_will_remove_from_hass(self):
        if self._session:
            await self._session.close()
