import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cartography.intel.github.app_auth import make_credential
from cartography.intel.github.util import fetch_all

logger = logging.getLogger(__name__)

REPO_STATE_GRAPHQL = """
    query($login: String!, $cursor: String, $count: Int!) {
        organization(login: $login) {
            url
            login
            repositories(first: $count, after: $cursor) {
                pageInfo {
                    endCursor
                    hasNextPage
                }
                nodes {
                    name
                    pushedAt
                    defaultBranchRef {
                        name
                        target {
                            oid
                        }
                    }
                }
            }
        }
        rateLimit {
            limit
            cost
            remaining
            resetAt
        }
    }
    """


@dataclass(frozen=True)
class RepoState:
    head_oid: str
    default_branch: str | None
    pushed_at: datetime | None


RepoStates = dict[tuple[str, str], RepoState]


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def transform_repo_states(organization: str, nodes: list[Any]) -> RepoStates:
    states: RepoStates = {}
    for node in nodes:
        if not node or not node.get("name"):
            continue
        branch = node.get("defaultBranchRef") or {}
        oid = (branch.get("target") or {}).get("oid")
        if not oid:
            continue
        states[(organization.lower(), node["name"].lower())] = RepoState(
            head_oid=oid,
            default_branch=branch.get("name"),
            pushed_at=parse_github_datetime(node.get("pushedAt")),
        )
    return states


def get_repo_states(github_config: str) -> RepoStates:
    """
    List every repository's default-branch HEAD and last push. Organizations
    that fail here are fetched without the cache rather than failing the sync.
    """
    states: RepoStates = {}
    auth_tokens = json.loads(base64.b64decode(github_config).decode())
    for auth_data in auth_tokens["organization"]:
        organization = auth_data["name"]
        try:
            data, _ = fetch_all(
                make_credential(auth_data),
                auth_data["url"],
                organization,
                REPO_STATE_GRAPHQL,
                "repositories",
                count=100,
            )
        except Exception:
            logger.warning(
                "Could not list repository state for GitHub org %s; "
                "fetching it without the cache.",
                organization,
                exc_info=True,
            )
            continue
        org_states = transform_repo_states(organization, data.nodes)
        logger.info(
            "Listed %d repositories with a default branch in GitHub org %s",
            len(org_states),
            organization,
        )
        states.update(org_states)
    return states
