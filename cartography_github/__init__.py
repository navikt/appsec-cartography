import logging
from datetime import timedelta

import neo4j

import cartography.intel.github
from cartography.config import Config
from cartography.util import timeit
from cartography_github.cache import Neo4jFetchCache
from cartography_github.fetchers import CachedGitHubFetches
from cartography_github.metadata import get_repo_states

logger = logging.getLogger(__name__)


@timeit
def start_github_ingestion(
    neo4j_session: neo4j.Session,
    config: Config,
    *,
    use_cache: bool = True,
    max_age: timedelta = timedelta(days=7),
    manifest_settle: timedelta = timedelta(hours=6),
) -> None:
    """
    Run upstream GitHub ingestion, replaying cached API responses for
    repositories whose default branch has not changed since they were cached.
    """
    if not config.github_config or not use_cache:
        cartography.intel.github.start_github_ingestion(neo4j_session, config)
        return

    cache = Neo4jFetchCache(neo4j_session)
    cache.ensure_index()
    fetches = CachedGitHubFetches(
        cache,
        get_repo_states(config.github_config),
        max_age=max_age,
        manifest_settle=manifest_settle,
    )
    try:
        with fetches.installed():
            cartography.intel.github.start_github_ingestion(neo4j_session, config)
    finally:
        fetches.log_stats()
    pruned = cache.prune(2 * max_age.total_seconds())
    logger.info("Pruned %d expired GitHub fetch cache entries", pruned)
