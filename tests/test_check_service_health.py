import pytest

from scripts import check_service_health as health


class FakeSettings:
    neo4j_uri = "bolt://neo4j.local:7687"
    neo4j_user = "neo4j"
    neo4j_database = "sentinel"
    milvus_uri = "http://milvus.local:19530"

    def require_neo4j_password(self) -> str:
        return "neo4j-secret"

    def optional_milvus_token(self) -> str | None:
        return "milvus-secret"


class FakeNeo4jResult:
    def __init__(self) -> None:
        self.consumed = False

    async def single(self) -> dict[str, int]:
        self.consumed = True
        return {"ok": 1}


class FakeNeo4jSession:
    def __init__(self) -> None:
        self.database = ""
        self.query = ""
        self.result = FakeNeo4jResult()

    async def __aenter__(self) -> "FakeNeo4jSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def run(self, query: str) -> FakeNeo4jResult:
        self.query = query
        return self.result


class FakeNeo4jDriver:
    def __init__(self) -> None:
        self.session_obj = FakeNeo4jSession()
        self.closed = False

    def session(self, *, database: str) -> FakeNeo4jSession:
        self.session_obj.database = database
        return self.session_obj

    async def close(self) -> None:
        self.closed = True


class FakeMilvusClient:
    def __init__(self, *, uri: str, token: str | None) -> None:
        self.uri = uri
        self.token = token
        self.closed = False

    def list_collections(self) -> list[str]:
        return []

    def close(self) -> None:
        self.closed = True


def make_factories(
    *,
    neo4j_driver: FakeNeo4jDriver | None = None,
    milvus_client: FakeMilvusClient | None = None,
) -> health.ServiceFactories:
    neo4j_driver = neo4j_driver or FakeNeo4jDriver()
    milvus_client = milvus_client or FakeMilvusClient(
        uri="http://milvus.local:19530",
        token="milvus-secret",
    )

    return health.ServiceFactories(
        neo4j_driver_factory=lambda uri, auth: neo4j_driver,
        milvus_client_factory=lambda **kwargs: milvus_client,
    )


def test_main_reports_all_services_pass_without_leaking_secrets(capsys) -> None:
    settings = FakeSettings()

    exit_code = health.main(
        settings_provider=lambda: settings,
        factories=make_factories(),
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[PASS] Neo4j bolt://neo4j.local:7687 database=sentinel" in captured.out
    assert "[PASS] Milvus http://milvus.local:19530" in captured.out
    assert "neo4j-secret" not in captured.out
    assert "milvus-secret" not in captured.out
    assert "password=***" in captured.out
    assert "token=***" in captured.out


def test_main_returns_nonzero_when_neo4j_check_fails(capsys) -> None:
    settings = FakeSettings()

    class FailingNeo4jDriver(FakeNeo4jDriver):
        async def close(self) -> None:
            self.closed = True

        def session(self, *, database: str) -> FakeNeo4jSession:
            raise RuntimeError("Neo4j connection refused")

    neo4j_driver = FailingNeo4jDriver()
    exit_code = health.main(
        settings_provider=lambda: settings,
        factories=make_factories(neo4j_driver=neo4j_driver),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "[FAIL] Neo4j" in captured.out


@pytest.mark.asyncio
async def test_checks_close_clients_after_success() -> None:
    settings = FakeSettings()
    neo4j_driver = FakeNeo4jDriver()
    milvus_client = FakeMilvusClient(
        uri="http://milvus.local:19530",
        token="milvus-secret",
    )
    factories = make_factories(
        neo4j_driver=neo4j_driver,
        milvus_client=milvus_client,
    )

    results = await health.run_checks(settings, factories)

    assert all(result.ok for result in results)
    assert neo4j_driver.closed is True
    assert milvus_client.closed is True
    assert neo4j_driver.session_obj.database == "sentinel"
    assert neo4j_driver.session_obj.query == "RETURN 1 AS ok"
    assert neo4j_driver.session_obj.result.consumed is True
    assert milvus_client.uri == "http://milvus.local:19530"
    assert milvus_client.token == "milvus-secret"
