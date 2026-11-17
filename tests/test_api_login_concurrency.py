"""Regressions for concurrent and cancelled Deco authentication attempts."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import UnexpectedApiException


def _api() -> TplinkDecoApi:
    """Construct a Deco client without network access or real credentials."""
    return TplinkDecoApi(
        session=MagicMock(),
        host="http://192.0.2.1",
        username="test-admin",
        password="synthetic-test-password",
        verify_ssl=True,
    )


@pytest.mark.asyncio
async def test_concurrent_login_waiters_share_one_successful_attempt() -> None:
    """Only the owner performs authentication while all waiters can join."""
    api = _api()
    started = asyncio.Event()
    release = asyncio.Event()

    async def _login() -> None:
        """Block the single mocked login until both waiters are attached."""
        started.set()
        await release.wait()

    api._async_login = AsyncMock(side_effect=_login)
    owner = asyncio.create_task(api.async_login())
    await asyncio.wait_for(started.wait(), timeout=2)
    waiters = [asyncio.create_task(api.async_login()) for _ in range(2)]
    await asyncio.sleep(0)
    release.set()

    await asyncio.wait_for(asyncio.gather(owner, *waiters), timeout=2)

    api._async_login.assert_awaited_once_with()
    assert api._login_future is None


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_abort_the_shared_login() -> None:
    """Cancel only the waiting caller while the owner completes normally."""
    api = _api()
    started = asyncio.Event()
    release = asyncio.Event()

    async def _login() -> None:
        """Hold the owner until its sibling waiter has been cancelled."""
        started.set()
        await release.wait()

    api._async_login = AsyncMock(side_effect=_login)
    owner = asyncio.create_task(api.async_login())
    await asyncio.wait_for(started.wait(), timeout=2)
    waiter = asyncio.create_task(api.async_login())
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, timeout=2)

    assert not owner.done()
    assert api._login_future is not None
    assert not api._login_future.cancelled()

    release.set()
    await asyncio.wait_for(owner, timeout=2)
    assert api._login_future is None
    api._async_login.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cancelled_owner_releases_waiter_and_allows_clean_relogin() -> None:
    """Clear a partially established session and release all queued callers."""
    api = _api()
    started = asyncio.Event()
    release = asyncio.Event()
    login_attempts = 0

    async def _login() -> None:
        """Simulate partial authentication followed by a later valid attempt."""
        nonlocal login_attempts
        login_attempts += 1
        if login_attempts == 1:
            api._seq = 7
            api._stok = "synthetic-partial-token"
            api._cookie = "sysauth=synthetic-partial-cookie"
            started.set()
            await release.wait()
            return
        api._seq = 11
        api._stok = "synthetic-refreshed-token"
        api._cookie = "sysauth=synthetic-refreshed-cookie"

    api._async_login = AsyncMock(side_effect=_login)
    owner = asyncio.create_task(api.async_login())
    await asyncio.wait_for(started.wait(), timeout=2)
    waiter = asyncio.create_task(api.async_login())
    await asyncio.sleep(0)

    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner, timeout=2)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, timeout=2)

    assert api._login_future is None
    assert (api._stok, api._cookie, api._seq) == (None, None, None)

    await asyncio.wait_for(api.async_login(), timeout=2)
    assert (api._stok, api._cookie, api._seq) == (
        "synthetic-refreshed-token",
        "sysauth=synthetic-refreshed-cookie",
        11,
    )
    assert login_attempts == 2
    assert api._login_future is None


@pytest.mark.asyncio
async def test_login_failure_reaches_all_waiters_and_permits_retry() -> None:
    """Broadcast the original error without leaving a blocked future behind."""
    api = _api()
    started = asyncio.Event()
    release = asyncio.Event()
    error = UnexpectedApiException("synthetic login failure")

    async def _failed_login() -> None:
        """Raise only after a second login caller joins the shared future."""
        started.set()
        await release.wait()
        raise error

    api._async_login = AsyncMock(side_effect=_failed_login)
    owner = asyncio.create_task(api.async_login())
    await asyncio.wait_for(started.wait(), timeout=2)
    waiter = asyncio.create_task(api.async_login())
    await asyncio.sleep(0)
    release.set()

    failures = await asyncio.wait_for(
        asyncio.gather(owner, waiter, return_exceptions=True),
        timeout=2,
    )

    assert failures == [error, error]
    assert failures[0] is failures[1]
    assert api._login_future is None
    api._async_login.assert_awaited_once_with()

    api._async_login = AsyncMock(return_value=None)
    await asyncio.wait_for(api.async_login(), timeout=2)
    api._async_login.assert_awaited_once_with()
    assert api._login_future is None
