import gzip
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import neo4j

logger = logging.getLogger(__name__)

CACHE_LABEL = "AppsecGitHubFetchCache"
# Larger payloads (e.g. huge lockfiles) are fetched every run instead of cached.
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CacheEntry:
    payload: Any
    oid: str
    fetched_at: float


class Neo4jFetchCache:
    """
    Raw GitHub API responses stored as nodes in the same Neo4j database.

    Cartography's cleanup jobs only touch their own labels, so these nodes
    survive syncs. Wiping the database simply means a cold cache.
    """

    def __init__(self, neo4j_session: neo4j.Session) -> None:
        self._session = neo4j_session

    def ensure_index(self) -> None:
        self._session.run(
            f"CREATE INDEX appsec_github_fetch_cache_id IF NOT EXISTS "
            f"FOR (n:{CACHE_LABEL}) ON (n.id)",
        ).consume()

    def get(self, key: str, fingerprint: str) -> CacheEntry | None:
        record = self._session.run(
            f"MATCH (n:{CACHE_LABEL} {{id: $key}}) "
            "RETURN n.fingerprint AS fingerprint, n.oid AS oid, "
            "n.fetched_at AS fetched_at, n.payload AS payload",
            key=key,
        ).single()
        if record is None or record["fingerprint"] != fingerprint:
            return None
        try:
            payload = json.loads(gzip.decompress(record["payload"]))
        except (OSError, TypeError, ValueError):
            logger.warning("Ignoring unreadable GitHub fetch cache entry %s", key)
            return None
        return CacheEntry(payload, record["oid"], record["fetched_at"])

    def put(
        self,
        key: str,
        fingerprint: str,
        oid: str,
        payload: Any,
        fetched_at: float,
    ) -> bool:
        data = gzip.compress(json.dumps(payload, separators=(",", ":")).encode())
        if len(data) > MAX_PAYLOAD_BYTES:
            logger.debug("Not caching %s: %d compressed bytes", key, len(data))
            return False
        self._session.run(
            f"MERGE (n:{CACHE_LABEL} {{id: $key}}) "
            "SET n.fingerprint = $fingerprint, n.oid = $oid, "
            "n.fetched_at = $fetched_at, n.payload = $payload",
            key=key,
            fingerprint=fingerprint,
            oid=oid,
            fetched_at=fetched_at,
            payload=data,
        ).consume()
        return True

    def prune(self, older_than_seconds: float, now: float | None = None) -> int:
        cutoff = (time.time() if now is None else now) - older_than_seconds
        summary = self._session.run(
            f"MATCH (n:{CACHE_LABEL}) WHERE n.fetched_at < $cutoff DETACH DELETE n",
            cutoff=cutoff,
        ).consume()
        return summary.counters.nodes_deleted
