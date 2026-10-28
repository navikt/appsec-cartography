import argparse
import logging
import os
from functools import partial

from cartography.config import Config
from cartography.sync import Sync
from cartography.sync import run_with_config

from cartography_nais import start_nais_ingestion


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sync Nais into Cartography")
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password-env-var", default="NEO4J_PASSWORD")
    parser.add_argument("--neo4j-database")
    parser.add_argument("--nais-base-url", default=os.environ.get("NAIS_BASE_URL"))
    parser.add_argument(
        "--nais-token-path",
        default=os.environ.get("NAIS_SERVICE_ACCOUNT_TOKEN_PATH"),
    )
    args = parser.parse_args(argv)
    if not args.nais_base_url or not args.nais_token_path:
        parser.error("Nais base URL and token path must be configured")
    password = os.environ.get(args.neo4j_password_env_var)
    if not password:
        parser.error(f"Missing Neo4j password in {args.neo4j_password_env_var}")

    sync = Sync()
    sync.add_stage(
        "nais",
        partial(
            start_nais_ingestion,
            base_url=args.nais_base_url,
            token_path=args.nais_token_path,
        ),
    )
    return run_with_config(
        sync,
        Config(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=password,
            neo4j_database=args.neo4j_database,
        ),
    )
