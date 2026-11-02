import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

from cartography.intel.github.app_auth import AppCredential
from cartography_github.auth import LockedCredential


def test_parallel_requests_share_a_single_installation_token_refresh(monkeypatch):
    credential = AppCredential("client", "test-private-key", "installation")
    refresh = Mock()

    def refresh_token():
        time.sleep(0.02)
        credential._token = "test-installation-token"
        credential._token_expires_at = time.time() + 3600
        refresh()

    monkeypatch.setattr(credential, "_refresh_token", refresh_token)
    locked = LockedCredential(credential)
    ready = Barrier(4)

    def get_token():
        ready.wait(timeout=5)
        return locked.get_token()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: get_token(), range(4)))

    assert results == ["test-installation-token"] * 4
    refresh.assert_called_once()
