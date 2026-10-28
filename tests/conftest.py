import pytest
from testcontainers.community.neo4j import Neo4jContainer


@pytest.fixture(scope="session")
def neo4j_driver():
    with Neo4jContainer("neo4j:5-community") as container:
        with container.get_driver() as driver:
            yield driver


@pytest.fixture
def neo4j_session(neo4j_driver):
    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
        try:
            yield session
        finally:
            session.run("MATCH (n) DETACH DELETE n").consume()
