"""Tests of the config flow, reauth, reconfigure, options and setup of the entry."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lumo.config_flow import normalize_host
from custom_components.lumo.const import (
    CONF_ACCOUNTS,
    CONF_ALLOW_HOMEWORK_WRITE,
    CONF_ENABLE_GRADES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    DOMAIN,
)

from .fake_server import PASSWORD, FakeLumo


def _conn(url: str, password: str = PASSWORD) -> dict:
    parsed = urlparse(url)
    return {
        CONF_HOST: parsed.hostname,
        CONF_PORT: parsed.port,
        CONF_SSL: False,
        CONF_PASSWORD: password,
    }


def _entry(url: str, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=_conn(url),
        options={
            CONF_ACCOUNTS: ["k3x9ab"],
            CONF_ENABLE_GRADES: False,
            CONF_ALLOW_HOMEWORK_WRITE: False,
            **options,
        },
        unique_id=f"{urlparse(url).hostname}:{urlparse(url).port}",
        title="Lumo",
    )


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("lumo.local", "lumo.local"),
        ("  http://lumo.local:8080/ ", "lumo.local"),
        ("https://lumo.example.org/app", "lumo.example.org"),
        ("192.168.1.50:8080", "192.168.1.50"),
        ("[::1]:8080", "::1"),
        ("fe80::1", "fe80::1"),
    ],
)
def test_normalize_host(typed: str, expected: str) -> None:
    assert normalize_host(typed) == expected


async def test_user_flow_with_account_choice(
    hass: HomeAssistant, fake: tuple[FakeLumo, str]
) -> None:
    _, url = fake
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], _conn(url))
    assert result["step_id"] == "accounts"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNTS: ["p7q2mz"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == PASSWORD
    # both switches are off by default
    assert result["options"] == {
        CONF_ACCOUNTS: ["p7q2mz"],
        CONF_ENABLE_GRADES: False,
        CONF_ALLOW_HOMEWORK_WRITE: False,
    }
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert list(entry.runtime_data.coordinators) == ["p7q2mz"]
    await _unload(hass, entry)


async def test_single_account_skips_the_choice(
    hass: HomeAssistant, fake: tuple[FakeLumo, str]
) -> None:
    server, url = fake
    del server.accounts[1]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _conn(url))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ACCOUNTS] == ["k3x9ab"]
    await hass.async_block_till_done()
    await _unload(hass, result["result"])


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({CONF_PASSWORD: "wrong"}, "invalid_auth"),
        ({CONF_PORT: 1}, "cannot_connect"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, fake: tuple[FakeLumo, str], override: dict, error: str
) -> None:
    _, url = fake
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**_conn(url), **override}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_user_flow_no_accounts(hass: HomeAssistant, fake: tuple[FakeLumo, str]) -> None:
    server, url = fake
    server.accounts.clear()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _conn(url))
    assert result["errors"] == {"base": "no_accounts"}


async def test_user_flow_not_lumo(hass: HomeAssistant, fake: tuple[FakeLumo, str]) -> None:
    server, url = fake
    original = server.healthz

    async def other(request):
        from aiohttp import web

        return web.json_response({"status": "ok", "app": "something else"})

    server.healthz = other  # type: ignore[method-assign]
    await server.stop()
    url = await server.start()
    server.healthz = original  # type: ignore[method-assign]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _conn(url))
    assert result["errors"] == {"base": "not_lumo"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, fake: tuple[FakeLumo, str]
) -> None:
    _, url = fake
    entry = _entry(url)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _conn(url))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    await _unload(hass, entry)


async def test_setup_with_wrong_password_starts_reauth(
    hass: HomeAssistant, fake: tuple[FakeLumo, str]
) -> None:
    _, url = fake
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_conn(url, "changed"),
        options={CONF_ACCOUNTS: ["k3x9ab"]},
        unique_id="x",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_setup_retries_when_server_is_down(hass: HomeAssistant, socket_enabled: None) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "127.0.0.1", CONF_PORT: 1, CONF_SSL: False, CONF_PASSWORD: "x"},
        options={CONF_ACCOUNTS: ["k3x9ab"]},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_reauth_flow(hass: HomeAssistant, fake: tuple[FakeLumo, str]) -> None:
    _, url = fake
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_conn(url, "changed"),
        options={CONF_ACCOUNTS: ["k3x9ab"]},
        unique_id="x",
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == PASSWORD
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await _unload(hass, entry)


async def test_reconfigure_flow(hass: HomeAssistant, fake: tuple[FakeLumo, str]) -> None:
    _, url = fake
    entry = _entry(url)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    # a different server is refused
    other = {**_conn(url), CONF_HOST: "localhost"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], other)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_server"

    result = await entry.start_reconfigure_flow(hass)
    new_password = {**_conn(url), CONF_SSL: False}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new_password)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    await _unload(hass, entry)


async def test_options_flow_switches_and_reloads(
    hass: HomeAssistant, fake: tuple[FakeLumo, str]
) -> None:
    server, url = fake
    entry = _entry(url)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert "grades" not in [p for _, p in server.requests]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    # all children of the server are offered, not only the selected one
    accounts_field = next(k for k in result["data_schema"].schema if k == CONF_ACCOUNTS)
    offered = result["data_schema"].schema[accounts_field].validators[0].options
    assert set(offered) == {"k3x9ab", "p7q2mz"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ACCOUNTS: ["k3x9ab", "p7q2mz"],
            CONF_ENABLE_GRADES: True,
            CONF_ALLOW_HOMEWORK_WRITE: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.coordinators) == {"k3x9ab", "p7q2mz"}
    coordinator = entry.runtime_data.coordinators["k3x9ab"]
    assert coordinator.enable_grades and coordinator.allow_homework_write
    assert "grades" in [p for _, p in server.requests]
    await _unload(hass, entry)


async def test_options_reject_empty_selection(
    hass: HomeAssistant, fake: tuple[FakeLumo, str]
) -> None:
    _, url = fake
    entry = _entry(url)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    from homeassistant.data_entry_flow import InvalidData

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_ACCOUNTS: [], CONF_ENABLE_GRADES: False, CONF_ALLOW_HOMEWORK_WRITE: False},
        )
    hass.config_entries.options.async_abort(result["flow_id"])
    await _unload(hass, entry)


async def test_vanished_account_is_skipped(hass: HomeAssistant, fake: tuple[FakeLumo, str]) -> None:
    _, url = fake
    entry = _entry(url, **{CONF_ACCOUNTS: ["k3x9ab", "gone42"]})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert list(entry.runtime_data.coordinators) == ["k3x9ab"]
    await _unload(hass, entry)
