"""Tests that example config files match documented project boundaries."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def test_config_examples_match_compose_service_defaults() -> None:
    config_example = _load_yaml("config/config.example.yaml")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    neo4j_compose = _load_yaml("docker/compose/neo4j.yaml")
    milvus_compose = _load_yaml("docker/compose/milvus.yaml")

    neo4j_auth = neo4j_compose["services"]["neo4j"]["environment"]["NEO4J_AUTH"]
    neo4j_user, neo4j_password = neo4j_auth.split("/", maxsplit=1)

    assert config_example["neo4j"]["uri"] == "bolt://localhost:7687"
    assert config_example["neo4j"]["user"] == neo4j_user
    assert f"NEO4J_PASSWORD={neo4j_password}" in env_example

    # 同一 compose 文件内的 healthcheck 必须与 NEO4J_AUTH 保持一致，
    # 否则容器会被自己的健康检查判死。
    healthcheck = " ".join(neo4j_compose["services"]["neo4j"]["healthcheck"]["test"])
    assert f"-u {neo4j_user}" in healthcheck
    assert f"-p {neo4j_password}" in healthcheck

    milvus_ports = milvus_compose["services"]["milvus"]["ports"]
    assert "19530:19530" in milvus_ports
    assert config_example["milvus"]["uri"] == "http://localhost:19530"


def test_attu_is_an_optional_compose_profile() -> None:
    milvus_compose = _load_yaml("docker/compose/milvus.yaml")
    attu = milvus_compose["services"]["attu"]

    assert attu["profiles"] == ["attu"]


def test_frontend_proxy_default_uses_dashboard_port_not_attu_port() -> None:
    frontend_env = (ROOT / "frontend/.env.example").read_text(encoding="utf-8")

    assert "VITE_PORT=3006" in frontend_env
    assert "VITE_API_PROXY_URL=http://127.0.0.1:8080" in frontend_env
    assert "VITE_API_PROXY_URL=http://127.0.0.1:8000" not in frontend_env


def test_env_example_guides_structured_config_usage() -> None:
    """.env.example 应引导用户把非密钥配置写进 config.yaml。

    只验证"引导到 config.yaml"这一关键概念存在，不再断言具体英文措辞，
    以免文档改写导致测试失败。
    """
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "config/config.yaml" in env_example


def test_optional_model_api_keys_are_blank_in_env_example() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "LLM_API_KEY=sk-your-api-key-here" in env_example
    assert "EMBEDDER_API_KEY=\n" in env_example
    assert "RERANKER_API_KEY=\n" in env_example


def test_ragflow_config_examples_match_reference_defaults() -> None:
    config_example = _load_yaml("config/config.example.yaml")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert config_example["ragflow"]["enabled"] is False
    assert config_example["ragflow"]["base_url"] == "http://127.0.0.1:9380"
    assert config_example["ragflow"]["top_k"] == 5
    assert config_example["ragflow"]["similarity_threshold"] == 0.2
    assert config_example["ragflow"]["vector_similarity_weight"] == 0.7
    assert config_example["ragflow"]["timeout_seconds"] == 15
    assert config_example["ragflow"]["max_context_chars"] == 4000
    assert config_example["ragflow"]["fail_open"] is True
    assert "RAGFLOW_API_KEY=" in env_example
    assert "RAGFLOW_MYSQL_PASSWORD=" in env_example
    assert "RAGFLOW_REDIS_PASSWORD=" in env_example
    assert "RAGFLOW_MINIO_PASSWORD=" in env_example
    assert "RAGFLOW_ELASTIC_PASSWORD=" in env_example


def test_ragflow_compose_environment_overrides_are_documented() -> None:
    env_docs = (ROOT / "docs/env-vars.md").read_text(encoding="utf-8")

    for name in [
        "RAGFLOW_IMAGE",
        "RAGFLOW_WEB_PORT",
        "RAGFLOW_API_PORT",
        "RAGFLOW_MYSQL_DATABASE",
        "RAGFLOW_MINIO_USER",
        "RAGFLOW_ES_JAVA_OPTS",
        "TZ",
    ]:
        assert f"`{name}`" in env_docs


def test_ragflow_sentinel_env_overrides_are_documented_separately() -> None:
    env_docs = (ROOT / "docs/env-vars.md").read_text(encoding="utf-8")

    for name in [
        "RAGFLOW_ENABLED",
        "RAGFLOW_BASE_URL",
        "RAGFLOW_DATASET_ID",
        "RAGFLOW_DATASET_IDS",
        "RAGFLOW_TOP_K",
        "RAGFLOW_SIMILARITY_THRESHOLD",
        "RAGFLOW_VECTOR_SIMILARITY_WEIGHT",
        "RAGFLOW_TIMEOUT_SECONDS",
        "RAGFLOW_MAX_CONTEXT_CHARS",
        "RAGFLOW_FAIL_OPEN",
    ]:
        assert f"`{name}`" in env_docs
    assert "本地 RAGFlow Docker profile 凭据" in env_docs
    assert "`RAGFLOW_MYSQL_PASSWORD`" in env_docs


def test_config_file_path_documentation_is_clear() -> None:
    """文档应说明配置文件路径是固定的 config/config.yaml。

    只验证关键概念（固定路径 + config.yaml）存在，不再断言精确中文措辞。
    'SENTINEL_CONFIG_FILE 环境变量不生效'这一行为已由 test_config.py 中的
    test_config_file_env_does_not_select_yaml_file 覆盖。
    """
    env_docs = (ROOT / "docs/env-vars.md").read_text(encoding="utf-8")
    ragflow_doc = (ROOT / "docs/ragflow.md").read_text(encoding="utf-8")

    assert "config/config.yaml" in env_docs
    assert "固定" in env_docs
    assert "config/config.yaml" in ragflow_doc


def test_ragflow_docs_explain_config_separation() -> None:
    """RAGFlow 文档应解释密钥放 .env、结构化配置放 config.yaml 的分离原则。"""
    ragflow_doc = (ROOT / "docs/ragflow.md").read_text(encoding="utf-8")

    assert "RAGFLOW_API_KEY" in ragflow_doc
    assert "config/config.yaml" in ragflow_doc
    assert "`.env`" in ragflow_doc


def test_ragflow_compose_is_included_and_loopback_only() -> None:
    docker_compose = _load_yaml("docker/docker-compose.yaml")
    dependency_compose = _load_yaml("docker/compose/dependencies.yaml")
    assert "compose/dependencies.yaml" in docker_compose["include"]
    assert "ragflow.yaml" in dependency_compose["include"]

    ragflow_compose = _load_yaml("docker/compose/ragflow.yaml")
    published_ports: list[str] = []
    for service in ragflow_compose["services"].values():
        published_ports.extend(str(port) for port in service.get("ports", []))

    assert published_ports
    assert all(port.startswith("127.0.0.1:") for port in published_ports)


def test_ragflow_compose_waits_for_dependency_healthchecks() -> None:
    ragflow_compose = _load_yaml("docker/compose/ragflow.yaml")
    services = ragflow_compose["services"]
    dependencies = [
        "ragflow-mysql",
        "ragflow-redis",
        "ragflow-minio",
        "ragflow-es",
    ]

    for dependency in dependencies:
        assert "healthcheck" in services[dependency]

    depends_on = services["ragflow"]["depends_on"]
    assert isinstance(depends_on, dict)
    for dependency in dependencies:
        assert depends_on[dependency]["condition"] == "service_healthy"
