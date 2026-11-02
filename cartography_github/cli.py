import argparse
import logging
import os
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
    parser.add_argument(
        "--github-parallel-workers",
        type=int,
        default=4,
        help="Maximum concurrent per-repository GitHub API fetches (default: 4)",
    )
    parser.add_argument(
        "--github-incremental-sync",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preserve unchanged repository data instead of refetching it",
    )
    args = parser.parse_args(argv)
    if args.github_parallel_workers < 1:
        parser.error("--github-parallel-workers must be at least 1")
    if args.github_commit_lookback_days < 0:
        parser.error("--github-commit-lookback-days must not be negative")
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
            parallel_workers=args.github_parallel_workers,
            incremental_sync=args.github_incremental_sync,
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
