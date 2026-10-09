import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_yaml(relative_path: str):
    return yaml.safe_load(read_text(relative_path))


def test_main_compose_defines_web_and_api_services():
    compose = read_yaml("docker/docker-compose.yaml")

    assert compose["include"] == ["compose/dependencies.yaml"]

    services = compose["services"]
    api = services["sentinel-api"]
    web = services["sentinel-web"]

    assert api["build"]["context"] == ".."
    assert api["build"]["dockerfile"] == "docker/Dockerfile.api"
    assert api["env_file"] == [{"path": "../.env", "required": False}]
    assert api["environment"] == {
        "NEO4J_URI": "bolt://neo4j:7687",
        "MILVUS_URI": "http://milvus:19530",
        "RAGFLOW_BASE_URL": "${RAGFLOW_BASE_URL:-http://ragflow:9380}",
    }
    assert api["volumes"] == ["../config:/app/config"]
    assert api["depends_on"]["neo4j"]["condition"] == "service_healthy"
    assert api["depends_on"]["milvus"]["condition"] == "service_healthy"

    assert web["build"]["context"] == ".."
    assert web["build"]["dockerfile"] == "docker/Dockerfile.web"
    assert web["ports"] == ["${SENTINEL_WEB_PORT:-8080}:80"]
    assert web["depends_on"]["sentinel-api"]["condition"] == "service_healthy"


def test_compose_build_arg_defaults_match_dockerfiles():
    """compose 与 Dockerfile 各自声明的默认镜像/索引/registry 必须一致。

    两侧独立维护同一份默认值；该守卫保证单侧修改（换镜像源、升版本）不会
    让镜像构建行为悄悄偏离 compose 部署的预期。
    """
    compose = read_yaml("docker/docker-compose.yaml")["services"]
    pairs = (
        (compose["sentinel-api"]["build"]["args"], "docker/Dockerfile.api"),
        (compose["sentinel-web"]["build"]["args"], "docker/Dockerfile.web"),
    )

    def compose_default(value: str) -> str:
        assert value.startswith("${") and ":-" in value, value
        return value[2:].split(":-", maxsplit=1)[1].removesuffix("}")

    def dockerfile_arg_defaults(text: str) -> dict[str, str]:
        defaults: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("ARG "):
                continue
            name, separator, value = stripped[len("ARG ") :].partition("=")
            assert separator, f"ARG without default: {stripped}"
            defaults[name.strip()] = value.strip()
        return defaults

    for compose_args, dockerfile_path in pairs:
        dockerfile_defaults = dockerfile_arg_defaults(read_text(dockerfile_path))
        for name, value in compose_args.items():
            assert name in dockerfile_defaults, (
                f"missing ARG {name} in {dockerfile_path}"
            )
            assert compose_default(value) == dockerfile_defaults[name], name


def test_dependency_compose_preserves_existing_dependency_fragments():
    compose = read_yaml("docker/compose/dependencies.yaml")

    assert compose["include"] == ["milvus.yaml", "neo4j.yaml", "ragflow.yaml"]
    assert compose["networks"] == {"devopsnetwork": {"driver": "bridge"}}


def test_documented_dependency_compose_commands_render():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")

    commands = [
        ["docker", "compose", "-f", "docker/compose/dependencies.yaml", "config"],
        [
            "docker",
            "compose",
            "-f",
            "docker/compose/dependencies.yaml",
            "config",
            "neo4j",
        ],
        [
            "docker",
            "compose",
            "-f",
            "docker/compose/dependencies.yaml",
            "config",
            "milvus",
        ],
        [
            "docker",
            "compose",
            "-f",
            "docker/compose/dependencies.yaml",
            "--profile",
            "attu",
            "config",
        ],
        [
            "docker",
            "compose",
            "-f",
            "docker/compose/dependencies.yaml",
            "--profile",
            "ragflow",
            "config",
        ],
    ]

    for command in commands:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        output = f"{result.stdout}\n{result.stderr}"
        unavailable_markers = [
            "could not be found in this WSL",
            "WSL integration",
            "Docker Desktop",
            "Cannot connect to the Docker daemon",
        ]
        if result.returncode != 0 and any(
            marker in output for marker in unavailable_markers
        ):
            pytest.skip(output.strip())
        assert result.returncode == 0, output


def test_dockerignore_excludes_local_state_and_secrets():
    ignored = set(read_text(".dockerignore").splitlines())

    assert ".env" in ignored
    assert ".worktrees" in ignored
    assert ".venv" in ignored
    assert "docker/volumes" in ignored
    assert "frontend/node_modules" in ignored
    assert "frontend/dist" in ignored
