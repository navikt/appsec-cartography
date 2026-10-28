"""
Minimal GraphQL client for the NAIS API.

Handles authenticated POST requests and cursor-based pagination.
"""

import logging
from typing import Any

import backoff
import requests

from cartography.util import backoff_handler

logger = logging.getLogger(__name__)

_MAX_TRIES = 4  # 1 initial + 3 retries (~1s, ~2s, ~4s backoff)


class NaisGraphQLClient:
    def __init__(self, token_path: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_path = token_path
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def _get_token(self) -> str:
        """Read the Bearer token fresh from disk on every call to handle short-lived projected tokens."""
        token = ""
        with open(self._token_path) as f:
            token = f.read().strip()
        if not token:
            raise ValueError(f"Nais token file is empty: {self._token_path}")
        return token

    def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Execute a GraphQL query and return the parsed JSON response.

        GraphQL errors abort the sync to avoid cleaning up incompletely fetched data.
        HTTP errors are raised and will be retried by paginate().
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._session.post(
            self._base_url,
            json=payload,
            timeout=60,
            headers={"Authorization": f"Bearer {self._get_token()}"},
        )
        if not response.ok:
            logger.error(
                "NAIS API error: status=%d url=%s body=%s",
                response.status_code,
                response.url,
                response.text[:500],
            )
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise RuntimeError(f"Nais GraphQL errors: {result['errors']}")

        data = result.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Nais GraphQL response is missing data")
        return data

    def paginate(
        self,
        query: str,
        data_path: list[str],
        variables: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> list[Any]:
        """
        Collect all nodes from a paginated connection.

        Each page request is retried with exponential backoff on HTTP errors.

        :param query: GraphQL query string. Must include $cursor and $first variables,
                      and expose pageInfo { hasNextPage endCursor } at the connection root.
        :param data_path: List of keys to drill into the response data to reach the connection
                          object, e.g. ["teams"] or ["environment", "workloads"].
        :param variables: Additional query variables to send on every request.
        :param page_size: Number of items to request per page.
        """
        variables = dict(variables or {})
        variables["first"] = page_size
        variables.setdefault("cursor", None)

        nodes: list[Any] = []
        page = 0

        @backoff.on_exception(
            backoff.expo,
            requests.exceptions.RequestException,
            max_tries=_MAX_TRIES,
            on_backoff=backoff_handler,
        )
        def _fetch_page() -> dict[str, Any]:
            return self.query(query, variables)

        while True:
            page += 1
            data = _fetch_page()

            if not data:
                raise RuntimeError(
                    f"Nais response is empty on page {page} for {data_path}"
                )

            # Drill down to the connection object
            connection: Any = data
            for key in data_path:
                if not isinstance(connection, dict) or not isinstance(
                    connection.get(key), dict
                ):
                    raise RuntimeError(f"Nais response is missing {data_path}")
                connection = connection[key]

            batch = connection.get("nodes")
            page_info = connection.get("pageInfo")
            if not isinstance(batch, list) or not isinstance(page_info, dict):
                raise RuntimeError(
                    f"Nais response has invalid pagination for {data_path}"
                )
            nodes.extend(batch)
            logger.debug(
                "NAIS paginate: path=%s page=%d fetched=%d total=%d",
                data_path,
                page,
                len(batch),
                len(nodes),
            )

            if page_info.get("hasNextPage") is False:
                break
            if page_info.get("hasNextPage") is not True or not page_info.get(
                "endCursor"
            ):
                raise RuntimeError(f"Nais response has invalid cursor for {data_path}")
            variables["cursor"] = page_info["endCursor"]

        return nodes
