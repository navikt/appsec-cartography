FROM europe-north1-docker.pkg.dev/cgr-nav/pull-through/nav.no/python:3.13-dev AS builder
USER root
COPY --from=ghcr.io/astral-sh/uv@sha256:87a04222b228501907f487b338ca6fc1514a93369bfce6930eb06c8d576e58a4 /uv /uvx /bin/
RUN mkdir -p /app && chown 1069:1069 /app
WORKDIR /app
ENV HOME=/app
COPY --chown=1069:1069 . /app/src
USER 1069
RUN uv export --frozen --no-dev --no-emit-project -o /app/constraints.txt --directory /app/src && \
    uv tool install --with-requirements /app/constraints.txt /app/src

FROM europe-north1-docker.pkg.dev/cgr-nav/pull-through/nav.no/python:3.13-dev AS production
USER root
RUN mkdir -p /app && chown 1069:1069 /app
COPY --from=builder --chown=1069:1069 /app/.local /app/.local
ENV HOME=/app
ENV PATH="/app/.local/bin:$PATH"
USER 1069
RUN cartography -h

ENTRYPOINT ["cartography"]
CMD ["-h"]
