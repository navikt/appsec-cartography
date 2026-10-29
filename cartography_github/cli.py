import argparse
import logging
import os
from datetime import timedelta
from functools import partial

import cartography.intel.create_indexes
from cartography.config import Config
from cartography.sync import Sync
from cartography.sync import run_with_config

from cartography_github import start_github_ingestion


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Sync GitHub into Cartography, skipping unchanged repository data",
    )
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password-env-var", default="NEO4J_PASSWORD")
    parser.add_argument("--neo4j-database")
    parser.add_argument("--github-config-env-var", default="GITHUB_CONFIG")
    parser.add_argument("--github-commit-lookback-days", type=int, default=30)
    parser.add_argument("--cache-max-age-days", type=float, default=7)
    parser.add_argument("--manifest-settle-hours", type=float, default=6)
    parser.add_argument(
        "--no-fetch-cache",
        action="store_true",
        help="Run plain upstream GitHub ingestion",
    )
    args = parser.parse_args(argv)
    password = os.environ.get(args.neo4j_password_env_var)
    if not password:
        parser.error(f"Missing Neo4j password in {args.neo4j_password_env_var}")
    github_config = os.environ.get(args.github_config_env_var)
    if not github_config:
        parser.error(f"Missing GitHub config in {args.github_config_env_var}")

    sync = Sync()
    sync.add_stage("create-indexes", cartography.intel.create_indexes.run)
    sync.add_stage(
        "github",
        partial(
            start_github_ingestion,
            use_cache=not args.no_fetch_cache,
            max_age=timedelta(days=args.cache_max_age_days),
            manifest_settle=timedelta(hours=args.manifest_settle_hours),
        ),
    )
    return run_with_config(
        sync,
        Config(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=password,
            neo4j_database=args.neo4j_database,
            github_config=github_config,
            github_commit_lookback_days=args.github_commit_lookback_days,
        ),
    )
