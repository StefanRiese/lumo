"""Config, reauth, reconfigure and options flow of the Lumo integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from . import LumoConfigEntry, base_url
from .api import (
    LumoAuthError,
    LumoClient,
    LumoConnectionError,
    LumoError,
    LumoRateLimitedError,
    LumoSetupRequiredError,
)
from .const import (
    CONF_ACCOUNTS,
    CONF_ALLOW_HOMEWORK_WRITE,
    CONF_ENABLE_GRADES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def normalize_host(host: str) -> str:
    """Strips a pasted scheme, path and port: `http://lumo.local:8080/` -> `lumo.local`."""
    host = host.strip()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host, flags=re.IGNORECASE)
    host = host.split("/", 1)[0]
    if host.startswith("["):  # [::1] or [::1]:8080
        return host.split("]", 1)[0].lstrip("[")
    if host.count(":") == 1:  # host:port
        host = host.split(":", 1)[0]
    return host


class CannotValidate(Exception):
    """Validation failed; `reason` is the key of the error text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def validate_connection(
    host: str, port: int, ssl: bool, password: str
) -> list[dict[str, Any]]:
    """Checks that a Lumo server answers and accepts the password; returns its accounts."""
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        client = LumoClient(session, base_url(host, port, ssl), password, timeout=15)
        try:
            health = await client.healthz()
            if not isinstance(health, dict) or health.get("app") != "lumo":
                raise CannotValidate("not_lumo")
            await client.login()
            return await client.accounts()
        except LumoAuthError as err:
            raise CannotValidate("invalid_auth") from err
        except LumoRateLimitedError as err:
            raise CannotValidate("rate_limited") from err
        except LumoSetupRequiredError as err:
            raise CannotValidate("setup_required") from err
        except LumoConnectionError as err:
            raise CannotValidate("cannot_connect") from err
        except (LumoError, ValueError, AttributeError) as err:
            _LOGGER.debug("Unexpected answer from the Lumo server: %s", err)
            raise CannotValidate("not_lumo") from err


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, False)): bool,
            vol.Required(CONF_PASSWORD): str,
        }
    )


def _accounts_schema(names: Mapping[str, str], selected: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ACCOUNTS, default=selected): vol.All(
                cv.multi_select(dict(names)), vol.Length(min=1)
            )
        }
    )


def _names(accounts: list[dict[str, Any]]) -> dict[str, str]:
    return {a["id"]: a.get("name") or a["id"] for a in accounts}


class LumoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one Lumo server; the children to follow are chosen in a second step."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection: dict[str, Any] = {}
        self._accounts: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LumoOptionsFlow:
        return LumoOptionsFlow()

    # --- new entry ------------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            await self.async_set_unique_id(f"{host.lower()}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            try:
                self._accounts = await validate_connection(
                    host, user_input[CONF_PORT], user_input[CONF_SSL], user_input[CONF_PASSWORD]
                )
            except CannotValidate as err:
                errors["base"] = err.reason
            else:
                if not self._accounts:
                    errors["base"] = "no_accounts"
                else:
                    self._connection = {**user_input, CONF_HOST: host}
                    if len(self._accounts) == 1:
                        return self._create([self._accounts[0]["id"]])
                    return await self.async_step_accounts()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(user_input or {}), user_input
            ),
            errors=errors,
        )

    async def async_step_accounts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        names = _names(self._accounts)
        if user_input is not None:
            return self._create(user_input[CONF_ACCOUNTS])
        return self.async_show_form(
            step_id="accounts", data_schema=_accounts_schema(names, list(names))
        )

    def _create(self, account_ids: list[str]) -> ConfigFlowResult:
        host = self._connection[CONF_HOST]
        return self.async_create_entry(
            title=f"Lumo ({host})",
            data=self._connection,
            options={
                CONF_ACCOUNTS: account_ids,
                CONF_ENABLE_GRADES: False,
                CONF_ALLOW_HOMEWORK_WRITE: False,
            },
        )

    # --- reauth / reconfigure -------------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_connection(
                    entry.data[CONF_HOST],
                    entry.data[CONF_PORT],
                    entry.data[CONF_SSL],
                    user_input[CONF_PASSWORD],
                )
            except CannotValidate as err:
                errors["base"] = err.reason
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            try:
                await validate_connection(
                    host, user_input[CONF_PORT], user_input[CONF_SSL], user_input[CONF_PASSWORD]
                )
            except CannotValidate as err:
                errors["base"] = err.reason
            else:
                unique_id = f"{host.lower()}:{user_input[CONF_PORT]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch(reason="wrong_server")
                return self.async_update_reload_and_abort(
                    entry, data_updates={**user_input, CONF_HOST: host}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or entry.data),
            errors=errors,
        )


class LumoOptionsFlow(OptionsFlow):
    """Children to follow plus the two opt-in switches (both off by default)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry: LumoConfigEntry = self.config_entry  # type: ignore[assignment]
        # All children of the server if the entry is loaded, otherwise only the selected ones.
        runtime = getattr(entry, "runtime_data", None)
        selected: list[str] = entry.options.get(CONF_ACCOUNTS, [])
        if runtime is not None:
            names = _names(list(runtime.server_accounts.values()))
        else:
            names = {account_id: account_id for account_id in selected}
        for account_id in selected:  # keep a selected child that vanished from the server
            names.setdefault(account_id, account_id)

        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNTS): vol.All(cv.multi_select(names), vol.Length(min=1)),
                vol.Required(CONF_ENABLE_GRADES): bool,
                vol.Required(CONF_ALLOW_HOMEWORK_WRITE): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_ACCOUNTS: selected,
                    CONF_ENABLE_GRADES: entry.options.get(CONF_ENABLE_GRADES, False),
                    CONF_ALLOW_HOMEWORK_WRITE: entry.options.get(CONF_ALLOW_HOMEWORK_WRITE, False),
                },
            ),
        )
