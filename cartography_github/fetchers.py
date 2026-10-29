import hashlib
import inspect
import logging
import time
from collections import Counter
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from types import ModuleType
from typing import Any

import neo4j

import cartography.intel.github.actions as gh_actions
import cartography.intel.github.codeowners as gh_codeowners
import cartography.intel.github.commits as gh_commits
import cartography.intel.github.repos as gh_repos
import cartography.intel.github.util as gh_util
from cartography_github.cache import CacheEntry
from cartography_github.cache import Neo4jFetchCache
from cartography_github.metadata import RepoState
from cartography_github.metadata import RepoStates

logger = logging.getLogger(__name__)

# Bump to invalidate every cached payload after a change in this package.
CACHE_SCHEMA_VERSION = "1"

FILE_CONTENT_PARAMS = ("token", "owner", "repo", "path", "ref", "base_url")
DEP_MANIFESTS_PARAMS = ("token", "api_url", "organization", "repo")
COMMITS_PARAMS = ("token", "api_url", "organization", "repo_name", "since_date")
# Upstream modules that read repository files through util.get_file_content.
FILE_CONTENT_MODULES: tuple[ModuleType, ...] = (gh_actions, gh_codeowners, gh_repos)

_DEFAULT_REST_BASE_URL = (
    inspect.signature(gh_util.get_file_content).parameters["base_url"].default
)


class IncompatibleUpstreamError(RuntimeError):
    """Upstream Cartography no longer matches the functions this package wraps."""


def _check_signature(func: Callable[..., Any], expected: tuple[str, ...]) -> None:
    actual = tuple(inspect.signature(func).parameters)
    if actual != expected:
        raise IncompatibleUpstreamError(
            f"{func.__module__}.{func.__qualname__} has parameters {actual}, "
            f"expected {expected}",
        )


def fingerprint(*parts: Any) -> str:
    """Hash the upstream code and queries that produce a cached payload."""
    digest = hashlib.sha256(CACHE_SCHEMA_VERSION.encode())
    for part in parts:
        text = part if isinstance(part, str) else inspect.getsource(part)
        digest.update(text.encode())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


class CachedGitHubFetches:
    """
    Replays raw GitHub API responses for repositories whose default branch has
    not moved, so upstream transform, load and cleanup run on identical input.
    """

    def __init__(
        self,
        cache: Neo4jFetchCache,
        repo_states: RepoStates,
        *,
        max_age: timedelta = timedelta(days=7),
        manifest_settle: timedelta = timedelta(hours=6),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cache = cache
        self._repo_states = repo_states
        self._max_age = max_age.total_seconds()
        self._manifest_settle = manifest_settle.total_seconds()
        self._clock = clock
        self._get_file_content = gh_util.get_file_content
        self._get_repo_dep_manifests = gh_repos._get_repo_dep_manifests
        self._get_repo_commits = gh_commits.get_repo_commits
        self._file_content_fingerprint = fingerprint(gh_util.get_file_content)
        self._dep_manifests_fingerprint = fingerprint(
            gh_repos._get_repo_dep_manifests,
            getattr(gh_repos, "_fetch_manifest_page", ""),
            gh_repos.GITHUB_REPO_DEP_MANIFESTS_PAGINATED_GRAPHQL,
        )
        self.stats: Counter[str] = Counter()

    @contextmanager
    def installed(self) -> Iterator[None]:
        replacements = self._replacements()
        saved: list[tuple[ModuleType, str, Any]] = []
        try:
            for module, name, replacement in replacements:
                saved.append((module, name, getattr(module, name)))
                setattr(module, name, replacement)
            yield
        finally:
            for module, name, original in reversed(saved):
                setattr(module, name, original)

    def _replacements(self) -> list[tuple[ModuleType, str, Callable[..., Any]]]:
        _check_signature(gh_util.get_file_content, FILE_CONTENT_PARAMS)
        _check_signature(gh_repos._get_repo_dep_manifests, DEP_MANIFESTS_PARAMS)
        _check_signature(gh_commits.get_repo_commits, COMMITS_PARAMS)
        for module in FILE_CONTENT_MODULES:
            if (
                getattr(module, "get_file_content", None)
                is not gh_util.get_file_content
            ):
                raise IncompatibleUpstreamError(
                    f"{module.__name__}.get_file_content is not "
                    "cartography.intel.github.util.get_file_content",
                )
        return [
            *[
                (module, "get_file_content", self.get_file_content)
                for module in FILE_CONTENT_MODULES
            ],
            (gh_repos, "_get_repo_dep_manifests", self.get_repo_dep_manifests),
            (gh_commits, "get_repo_commits", self.get_repo_commits),
        ]

    def log_stats(self) -> None:
        logger.info("GitHub fetch cache results: %s", dict(sorted(self.stats.items())))

    def _state(self, owner: str, repo: str) -> RepoState | None:
        return self._repo_states.get((owner.lower(), repo.lower()))

    def _max_age_for(self, key: str) -> float:
        # Spread expiry over the last quarter of the window so entries cached
        # in the same cold run are not all refetched in the same later run.
        spread = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return self._max_age * (1 - 0.25 * spread)

    def _load(self, key: str, fp: str, oid: str) -> CacheEntry | None:
        try:
            entry = self._cache.get(key, fp)
        except neo4j.exceptions.Neo4jError:
            logger.warning(
                "Could not read GitHub fetch cache entry %s", key, exc_info=True
            )
            return None
        if entry is None or entry.oid != oid:
            return None
        if self._clock() - entry.fetched_at >= self._max_age_for(key):
            return None
        return entry

    def _store(self, kind: str, key: str, fp: str, oid: str, payload: Any) -> None:
        try:
            stored = self._cache.put(key, fp, oid, payload, self._clock())
        except neo4j.exceptions.Neo4jError:
            logger.warning(
                "Could not write GitHub fetch cache entry %s", key, exc_info=True
            )
            stored = False
        if not stored:
            self.stats[f"{kind}.not_cached"] += 1

    def get_file_content(
        self,
        token: str,
        owner: str,
        repo: str,
        path: str,
        ref: str = "HEAD",
        base_url: str = _DEFAULT_REST_BASE_URL,
    ) -> str | None:
        state = self._state(owner, repo)
        if state is None or ref not in ("HEAD", state.default_branch):
            self.stats["file_content.bypass"] += 1
            return self._get_file_content(
                token, owner, repo, path, ref=ref, base_url=base_url
            )

        key = f"file:{owner.lower()}/{repo.lower()}:{path}"
        entry = self._load(key, self._file_content_fingerprint, state.head_oid)
        if entry is not None:
            self.stats["file_content.hit"] += 1
            return entry.payload["content"]

        self.stats["file_content.miss"] += 1
        # Pin the read to the listed commit so the cached content matches its key.
        content = self._get_file_content(
            token, owner, repo, path, ref=state.head_oid, base_url=base_url
        )
        self._store(
            "file_content",
            key,
            self._file_content_fingerprint,
            state.head_oid,
            {"content": content},
        )
        return content

    def get_repo_dep_manifests(
        self,
        token: str,
        api_url: str,
        organization: str,
        repo: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        state = self._state(organization, repo)
        if state is None:
            self.stats["dep_manifests.bypass"] += 1
            return self._get_repo_dep_manifests(token, api_url, organization, repo)

        key = f"dep-manifests:{organization.lower()}/{repo.lower()}"
        entry = self._load(key, self._dep_manifests_fingerprint, state.head_oid)
        if entry is not None:
            self.stats["dep_manifests.hit"] += 1
            return entry.payload["manifests"], True

        self.stats["dep_manifests.miss"] += 1
        manifests, cleanup_safe = self._get_repo_dep_manifests(
            token, api_url, organization, repo
        )
        if cleanup_safe and self._is_settled(state):
            self._store(
                "dep_manifests",
                key,
                self._dep_manifests_fingerprint,
                state.head_oid,
                {"manifests": manifests},
            )
        else:
            self.stats["dep_manifests.not_cached"] += 1
        return manifests, cleanup_safe

    def _is_settled(self, state: RepoState) -> bool:
        # GitHub builds the dependency graph and accepts CI dependency
        # submissions some time after a push, so recent results may be partial.
        if state.pushed_at is None:
            return True
        return self._clock() - state.pushed_at.timestamp() >= self._manifest_settle

    def get_repo_commits(
        self,
        token: str,
        api_url: str,
        organization: str,
        repo_name: str,
        since_date: datetime,
    ) -> list[dict[str, Any]]:
        state = self._state(organization, repo_name)
        if (
            state is not None
            and state.pushed_at is not None
            and state.pushed_at < since_date
        ):
            self.stats["commits.no_push_in_lookback"] += 1
            return []
        self.stats["commits.fetched"] += 1
        return self._get_repo_commits(
            token, api_url, organization, repo_name, since_date
        )
