# GitHub collector

Runs as `cartography-github`. It extracts the incremental and parallel
collection from `navikt/cartography@github-module` while reusing upstream
transforms, models, and unaffected ingestion stages. GitHub API fetches run with
four workers by default; Neo4j writes stay on the ingestion thread.

Incremental sync preserves existing workflow and dependency subgraphs when a
repository's push timestamp and default branch are unchanged, refreshing
cleanup timestamps on their nodes and relationships. Secrets, variables, and
environments are still refreshed for active repositories, and new secrets
trigger a workflow refetch so secret references are linked. Commit queries skip
repositories with no push in the lookback window. Bookmarks advance only after
the whole run succeeds; failed or incomplete dependency and workflow responses
keep their existing data and remain eligible for retry. Global repository
cleanup is skipped when a repository listing is incomplete. A first run without
compatible bookmarks still performs a full collection.

Use `--no-github-incremental-sync` for a full refresh, and
`--github-parallel-workers N` to change API concurrency. This is a local
collector, not a patch of the installed upstream modules. GitHub is pinned to
upstream `0.143.0` because the extension uses upstream internal helpers; run the
tests against the selected source before updating the pin.

Scheduled GitHub runs remain paused pending production verification. Run the
Naisjob manually after deployment to check runtime, completeness warnings,
and the logged stage durations before restoring its schedule. The previous
baseline fetch cache is no longer read or written; existing
`AppsecGitHubFetchCache` nodes are left untouched.
