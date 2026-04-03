"""Service orchestration - start/stop/health-check services for integration tests."""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


# Common service definitions with default health checks
KNOWN_SERVICES: dict[str, dict] = {
    "postgres": {
        "image": "postgres:16-alpine",
        "port": 5432,
        "env": {"POSTGRES_PASSWORD": "test", "POSTGRES_DB": "test"},
        "health_cmd": ["pg_isready", "-U", "postgres"],
        "test_env": {
            "DATABASE_URL": "postgres://postgres:test@localhost:5432/test",
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGUSER": "postgres",
            "PGPASSWORD": "test",
            "PGDATABASE": "test",
        },
    },
    "redis": {
        "image": "redis:7-alpine",
        "port": 6379,
        "health_cmd": ["redis-cli", "ping"],
        "test_env": {
            "REDIS_URL": "redis://localhost:6379",
        },
    },
    "mysql": {
        "image": "mysql:8",
        "port": 3306,
        "env": {"MYSQL_ROOT_PASSWORD": "test", "MYSQL_DATABASE": "test"},
        "health_cmd": ["mysqladmin", "ping", "-h", "localhost"],
        "test_env": {
            "DATABASE_URL": "mysql://root:test@localhost:3306/test",
        },
    },
    "mongodb": {
        "image": "mongo:7",
        "port": 27017,
        "test_env": {
            "MONGODB_URL": "mongodb://localhost:27017/test",
        },
    },
    "rabbitmq": {
        "image": "rabbitmq:3-management-alpine",
        "port": 5672,
        "test_env": {
            "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
        },
    },
    "elasticsearch": {
        "image": "elasticsearch:8.12.0",
        "port": 9200,
        "env": {"discovery.type": "single-node", "xpack.security.enabled": "false"},
        "test_env": {
            "ELASTICSEARCH_URL": "http://localhost:9200",
        },
    },
    "minio": {
        "image": "minio/minio:latest",
        "port": 9000,
        "env": {"MINIO_ROOT_USER": "minioadmin", "MINIO_ROOT_PASSWORD": "minioadmin"},
        "command": ["server", "/data"],
        "test_env": {
            "S3_ENDPOINT": "http://localhost:9000",
            "AWS_ACCESS_KEY_ID": "minioadmin",
            "AWS_SECRET_ACCESS_KEY": "minioadmin",
        },
    },
}


@dataclass
class ServiceConfig:
    """Configuration for a single service."""

    name: str
    image: str | None = None
    port: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    health_cmd: list[str] | None = None
    command: list[str] | None = None
    test_env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict | str) -> ServiceConfig:
        """Parse service config from bob.yaml.

        Can be just a name (string) for known services, or a dict with full config.
        """
        if isinstance(data, str):
            # Just a service name — look up in known services
            known = KNOWN_SERVICES.get(data, {})
            return cls(
                name=data,
                image=known.get("image"),
                port=known.get("port"),
                env=known.get("env", {}),
                health_cmd=known.get("health_cmd"),
                command=known.get("command"),
                test_env=known.get("test_env", {}),
            )

        return cls(
            name=name,
            image=data.get("image"),
            port=data.get("port"),
            env=data.get("env", {}),
            health_cmd=data.get("health_cmd"),
            command=data.get("command"),
            test_env=data.get("test_env", {}),
        )

    def to_dict(self) -> dict:
        d: dict = {"name": self.name}
        if self.image:
            d["image"] = self.image
        if self.port:
            d["port"] = self.port
        if self.env:
            d["env"] = self.env
        if self.test_env:
            d["test_env"] = self.test_env
        return d


@dataclass
class ServiceResult:
    """Result of a service operation."""

    name: str
    success: bool
    message: str = ""
    port: int | None = None
    env_vars: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "success": self.success, "message": self.message}
        if self.port:
            d["port"] = self.port
        if self.env_vars:
            d["env_vars"] = self.env_vars
        return d


def _container_name(service_name: str) -> str:
    return f"bob-test-{service_name}"


def _is_port_open(port: int, host: str = "localhost", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def start_services(
    services: list[ServiceConfig],
    project_path: Path | None = None,
) -> list[ServiceResult]:
    """Start services using docker run. Returns results with env vars to inject."""
    results: list[ServiceResult] = []

    for svc in services:
        container = _container_name(svc.name)

        # Check if the port is already open (service running natively or in another container)
        if svc.port and _is_port_open(svc.port):
            results.append(ServiceResult(
                name=svc.name,
                success=True,
                message=f"Already running on port {svc.port}",
                port=svc.port,
                env_vars=svc.test_env,
            ))
            continue

        # Check if bob's container is already running
        if _is_container_running(container):
            results.append(ServiceResult(
                name=svc.name,
                success=True,
                message="Container already running",
                port=svc.port,
                env_vars=svc.test_env,
            ))
            continue

        # If project has docker-compose with this service, use that
        if project_path and _compose_has_service(project_path, svc.name):
            result = _start_compose_service(project_path, svc)
            results.append(result)
            continue

        # Otherwise use docker run
        if not svc.image:
            results.append(ServiceResult(
                name=svc.name,
                success=False,
                message=f"Unknown service '{svc.name}' — specify an image in bob.yaml",
            ))
            continue

        result = _start_docker_service(svc, container)
        results.append(result)

    return results


def stop_services(services: list[ServiceConfig], project_path: Path | None = None) -> list[ServiceResult]:
    """Stop and remove service containers."""
    results: list[ServiceResult] = []

    for svc in services:
        container = _container_name(svc.name)

        # Try compose first
        if project_path and _compose_has_service(project_path, svc.name):
            try:
                subprocess.run(
                    ["docker", "compose", "stop", svc.name],
                    cwd=str(project_path),
                    capture_output=True,
                    timeout=30,
                )
                results.append(ServiceResult(name=svc.name, success=True, message="Stopped (compose)"))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                results.append(ServiceResult(name=svc.name, success=False, message="Failed to stop"))
            continue

        try:
            subprocess.run(
                ["docker", "rm", "-f", container],
                capture_output=True,
                timeout=15,
            )
            results.append(ServiceResult(name=svc.name, success=True, message="Stopped"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            results.append(ServiceResult(name=svc.name, success=False, message="Failed to stop"))

    return results


def wait_for_services(
    services: list[ServiceConfig],
    timeout: int = 30,
) -> list[ServiceResult]:
    """Wait for services to become healthy."""
    results: list[ServiceResult] = []
    deadline = time.monotonic() + timeout

    for svc in services:
        if not svc.port:
            results.append(ServiceResult(
                name=svc.name, success=True, message="No port to check",
            ))
            continue

        healthy = False
        while time.monotonic() < deadline:
            if _is_port_open(svc.port):
                healthy = True
                break
            time.sleep(0.5)

        if healthy:
            results.append(ServiceResult(
                name=svc.name,
                success=True,
                message=f"Healthy (port {svc.port})",
                port=svc.port,
                env_vars=svc.test_env,
            ))
        else:
            results.append(ServiceResult(
                name=svc.name,
                success=False,
                message=f"Timed out waiting for port {svc.port}",
                port=svc.port,
            ))

    return results


def collect_test_env(services: list[ServiceConfig]) -> dict[str, str]:
    """Collect all test environment variables from services."""
    env: dict[str, str] = {}
    for svc in services:
        env.update(svc.test_env)
    return env


def parse_services(data: list | None) -> list[ServiceConfig]:
    """Parse services from bob.yaml format.

    Supports:
      services: [postgres, redis]                    # known service names
      services:
        - postgres
        - name: custom-db
          image: postgres:15
          port: 5433
          test_env:
            DATABASE_URL: postgres://localhost:5433/test
    """
    if not data:
        return []

    configs: list[ServiceConfig] = []
    for item in data:
        if isinstance(item, str):
            known = KNOWN_SERVICES.get(item)
            if known:
                configs.append(ServiceConfig(
                    name=item,
                    image=known.get("image"),
                    port=known.get("port"),
                    env=known.get("env", {}),
                    health_cmd=known.get("health_cmd"),
                    command=known.get("command"),
                    test_env=known.get("test_env", {}),
                ))
            else:
                configs.append(ServiceConfig(name=item))
        elif isinstance(item, dict):
            name = item.get("name", item.get("image", "unknown"))
            configs.append(ServiceConfig(
                name=name,
                image=item.get("image"),
                port=item.get("port"),
                env=item.get("env", {}),
                health_cmd=item.get("health_cmd"),
                command=item.get("command"),
                test_env=item.get("test_env", {}),
            ))

    return configs


# --- Internal helpers ---


def _is_container_running(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _start_docker_service(svc: ServiceConfig, container_name: str) -> ServiceResult:
    """Start a service using docker run."""
    cmd = ["docker", "run", "-d", "--name", container_name]

    if svc.port:
        cmd.extend(["-p", f"{svc.port}:{svc.port}"])

    for key, val in svc.env.items():
        cmd.extend(["-e", f"{key}={val}"])

    cmd.append(svc.image)

    if svc.command:
        cmd.extend(svc.command)

    try:
        # Remove any existing stopped container with same name
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=10,
        )

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return ServiceResult(
                name=svc.name,
                success=True,
                message=f"Started ({svc.image})",
                port=svc.port,
                env_vars=svc.test_env,
            )
        return ServiceResult(
            name=svc.name,
            success=False,
            message=result.stderr.strip()[:200],
        )
    except subprocess.TimeoutExpired:
        return ServiceResult(name=svc.name, success=False, message="Timed out starting container")
    except FileNotFoundError:
        return ServiceResult(name=svc.name, success=False, message="Docker not found")


def _compose_has_service(project_path: Path, service_name: str) -> bool:
    """Check if docker-compose.yml defines a service with this name."""
    for compose_file in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        path = project_path / compose_file
        if path.exists():
            try:
                content = path.read_text()
                # Simple check — look for the service name as a key under services:
                import yaml
                data = yaml.safe_load(content)
                services = data.get("services", {})
                return service_name in services
            except Exception:
                pass
    return False


def _start_compose_service(project_path: Path, svc: ServiceConfig) -> ServiceResult:
    """Start a service from docker-compose."""
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", svc.name],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return ServiceResult(
                name=svc.name,
                success=True,
                message=f"Started via docker compose",
                port=svc.port,
                env_vars=svc.test_env,
            )
        return ServiceResult(
            name=svc.name,
            success=False,
            message=result.stderr.strip()[:200],
        )
    except subprocess.TimeoutExpired:
        return ServiceResult(name=svc.name, success=False, message="Timed out starting compose service")
    except FileNotFoundError:
        return ServiceResult(name=svc.name, success=False, message="Docker not found")
