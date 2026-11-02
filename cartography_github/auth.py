from threading import Lock

from cartography.intel.github.app_auth import GitHubCredential


class LockedCredential(GitHubCredential):
    """Serialize token refresh while allowing concurrent API requests."""

    def __init__(self, credential: GitHubCredential) -> None:
        self._credential = credential
        self._lock = Lock()

    def get_token(self) -> str:
        with self._lock:
            return self._credential.get_token()
