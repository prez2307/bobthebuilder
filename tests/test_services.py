"""Tests for service orchestration."""

import json
from pathlib import Path

import pytest
import yaml

from bobthebuilder.services import (
    KNOWN_SERVICES,
    ServiceConfig,
    ServiceResult,
    collect_test_env,
    parse_services,
)


class TestKnownServices:
    def test_postgres_defined(self):
        assert "postgres" in KNOWN_SERVICES
        pg = KNOWN_SERVICES["postgres"]
        assert pg["port"] == 5432
        assert pg["image"].startswith("postgres:")
        assert "DATABASE_URL" in pg["test_env"]

    def test_redis_defined(self):
        assert "redis" in KNOWN_SERVICES
        redis = KNOWN_SERVICES["redis"]
        assert redis["port"] == 6379
        assert "REDIS_URL" in redis["test_env"]

    def test_mysql_defined(self):
        assert "mysql" in KNOWN_SERVICES
        assert KNOWN_SERVICES["mysql"]["port"] == 3306

    def test_mongodb_defined(self):
        assert "mongodb" in KNOWN_SERVICES
        assert KNOWN_SERVICES["mongodb"]["port"] == 27017

    def test_minio_defined(self):
        assert "minio" in KNOWN_SERVICES
        assert "AWS_ACCESS_KEY_ID" in KNOWN_SERVICES["minio"]["test_env"]


class TestServiceConfig:
    def test_from_string_known(self):
        config = ServiceConfig.from_dict("postgres", "postgres")
        assert config.name == "postgres"
        assert config.image == "postgres:16-alpine"
        assert config.port == 5432
        assert "DATABASE_URL" in config.test_env

    def test_from_string_unknown(self):
        config = ServiceConfig.from_dict("custom", "custom")
        assert config.name == "custom"
        assert config.image is None

    def test_from_dict(self):
        config = ServiceConfig.from_dict("mydb", {
            "image": "postgres:15",
            "port": 5433,
            "env": {"POSTGRES_PASSWORD": "secret"},
            "test_env": {"DATABASE_URL": "postgres://localhost:5433/test"},
        })
        assert config.name == "mydb"
        assert config.image == "postgres:15"
        assert config.port == 5433
        assert config.test_env["DATABASE_URL"] == "postgres://localhost:5433/test"

    def test_to_dict(self):
        config = ServiceConfig(
            name="redis",
            image="redis:7",
            port=6379,
            test_env={"REDIS_URL": "redis://localhost:6379"},
        )
        d = config.to_dict()
        assert d["name"] == "redis"
        assert d["image"] == "redis:7"
        assert d["port"] == 6379
        assert d["test_env"]["REDIS_URL"] == "redis://localhost:6379"


class TestParseServices:
    def test_parse_string_list(self):
        services = parse_services(["postgres", "redis"])
        assert len(services) == 2
        assert services[0].name == "postgres"
        assert services[0].port == 5432
        assert services[1].name == "redis"
        assert services[1].port == 6379

    def test_parse_dict_list(self):
        services = parse_services([
            {"name": "mydb", "image": "postgres:15", "port": 5433},
        ])
        assert len(services) == 1
        assert services[0].name == "mydb"
        assert services[0].image == "postgres:15"

    def test_parse_mixed(self):
        services = parse_services([
            "redis",
            {"name": "custom-pg", "image": "postgres:14", "port": 5433,
             "test_env": {"DB_URL": "postgres://localhost:5433/test"}},
        ])
        assert len(services) == 2
        assert services[0].name == "redis"
        assert services[0].image == "redis:7-alpine"
        assert services[1].name == "custom-pg"
        assert services[1].port == 5433

    def test_parse_empty(self):
        assert parse_services(None) == []
        assert parse_services([]) == []

    def test_parse_unknown_service(self):
        services = parse_services(["unknown-thing"])
        assert len(services) == 1
        assert services[0].name == "unknown-thing"
        assert services[0].image is None

    def test_parse_from_bob_yaml(self):
        """Test the full round-trip from bob.yaml format."""
        bob_yaml_data = {
            "workspace": "test",
            "repos": [{
                "path": "./backend",
                "detected": {"ecosystem": "python", "package_manager": "uv"},
                "services": ["postgres", "redis"],
                "test_env": {"SECRET_KEY": "test-secret"},
            }],
        }
        from bobthebuilder.workspace import WorkspaceRepo
        repo = WorkspaceRepo.from_dict(bob_yaml_data["repos"][0])
        assert repo.services == ["postgres", "redis"]
        assert repo.test_env == {"SECRET_KEY": "test-secret"}

        services = parse_services(repo.services)
        assert len(services) == 2
        assert services[0].name == "postgres"


class TestCollectTestEnv:
    def test_merges_all_service_env(self):
        services = parse_services(["postgres", "redis"])
        env = collect_test_env(services)
        assert "DATABASE_URL" in env
        assert "REDIS_URL" in env
        assert env["DATABASE_URL"] == "postgres://postgres:test@localhost:5432/test"
        assert env["REDIS_URL"] == "redis://localhost:6379"

    def test_empty_services(self):
        env = collect_test_env([])
        assert env == {}

    def test_custom_env_override(self):
        services = [ServiceConfig(
            name="pg",
            test_env={"DATABASE_URL": "postgres://custom:5433/mydb"},
        )]
        env = collect_test_env(services)
        assert env["DATABASE_URL"] == "postgres://custom:5433/mydb"


class TestServiceResult:
    def test_to_dict(self):
        r = ServiceResult(
            name="postgres",
            success=True,
            message="Started",
            port=5432,
            env_vars={"DATABASE_URL": "postgres://localhost:5432/test"},
        )
        d = r.to_dict()
        assert d["name"] == "postgres"
        assert d["success"] is True
        assert d["port"] == 5432
        assert "DATABASE_URL" in d["env_vars"]

    def test_to_dict_failure(self):
        r = ServiceResult(name="redis", success=False, message="Docker not found")
        d = r.to_dict()
        assert d["success"] is False
        assert d["message"] == "Docker not found"


class TestBobYamlWithServices:
    """Test the full bob.yaml schema with services."""

    def test_workspace_repo_serialization(self):
        from bobthebuilder.workspace import WorkspaceRepo

        repo = WorkspaceRepo(
            path="./backend",
            detected_ecosystem="python",
            detected_package_manager="uv",
            services=["postgres", "redis"],
            test_env={"SECRET_KEY": "test", "DEBUG": "true"},
        )
        d = repo.to_dict()
        assert d["services"] == ["postgres", "redis"]
        assert d["test_env"]["SECRET_KEY"] == "test"

    def test_workspace_save_load_with_services(self, tmp_path):
        from bobthebuilder.workspace import Workspace, WorkspaceRepo, load_workspace

        ws = Workspace(
            name="test-ws",
            repos=[WorkspaceRepo(
                path="./api",
                detected_ecosystem="python",
                services=["postgres", "redis", "minio"],
                test_env={"APP_ENV": "test"},
            )],
        )
        ws.save(tmp_path / "bob.yaml")

        loaded = load_workspace(tmp_path / "bob.yaml")
        assert loaded.repos[0].services == ["postgres", "redis", "minio"]
        assert loaded.repos[0].test_env == {"APP_ENV": "test"}

    def test_bob_yaml_format(self, tmp_path):
        """Verify the YAML format looks right for humans."""
        from bobthebuilder.workspace import Workspace, WorkspaceRepo

        ws = Workspace(
            name="my-app",
            repos=[WorkspaceRepo(
                path="./backend",
                detected_ecosystem="python",
                detected_package_manager="uv",
                services=["postgres", "redis"],
                test_env={"DATABASE_URL": "postgres://localhost:5432/test"},
                hooks={"pre_test": "python manage.py migrate"},
            )],
        )
        ws.save(tmp_path / "bob.yaml")
        content = (tmp_path / "bob.yaml").read_text()

        raw = yaml.safe_load(content)
        repo = raw["repos"][0]
        assert repo["services"] == ["postgres", "redis"]
        assert repo["test_env"]["DATABASE_URL"] == "postgres://localhost:5432/test"
        assert repo["hooks"]["pre_test"] == "python manage.py migrate"
