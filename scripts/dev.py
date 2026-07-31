#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "dev"


@dataclass(frozen=True)
class Service:
    name: str
    command: list[str]
    cwd: Path
    port_env: str | None = None
    default_port: int | None = None
    required_path: Path | None = None


SERVICES = {
    "backend": Service(
        name="backend",
        command=[".venv/bin/python", "backend/manage.py", "runserver", "127.0.0.1:{port}"],
        cwd=ROOT,
        port_env="BACKEND_PORT",
        default_port=8000,
        required_path=ROOT / "backend" / "manage.py",
    ),
    "frontend": Service(
        name="frontend",
        command=["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "{port}"],
        cwd=ROOT / "frontend",
        port_env="FRONTEND_PORT",
        default_port=5173,
        required_path=ROOT / "frontend" / "package.json",
    ),
    "celery": Service(
        name="celery",
        command=[
            "../.venv/bin/celery",
            "-A",
            "config",
            "worker",
            "-l",
            "info",
            "--pool=solo",
            "--concurrency=1",
        ],
        cwd=ROOT / "backend",
        required_path=ROOT / "backend" / "config" / "celery.py",
    ),
    "network-mcp": Service(
        name="network-mcp",
        command=[".venv/bin/python", "-m", "mcp_servers.network"],
        cwd=ROOT,
        port_env="NETWORK_MCP_PORT",
        default_port=8101,
        required_path=ROOT / "mcp_servers" / "network" / "__main__.py",
    ),
    "customer-mcp": Service(
        name="customer-mcp",
        command=[".venv/bin/python", "-m", "mcp_servers.customer"],
        cwd=ROOT,
        port_env="CUSTOMER_MCP_PORT",
        default_port=8102,
        required_path=ROOT / "mcp_servers" / "customer" / "__main__.py",
    ),
    "rule-mcp": Service(
        name="rule-mcp",
        command=[".venv/bin/python", "-m", "mcp_servers.rules"],
        cwd=ROOT,
        port_env="RULE_MCP_PORT",
        default_port=8103,
        required_path=ROOT / "mcp_servers" / "rules" / "__main__.py",
    ),
    "compensation-mcp": Service(
        name="compensation-mcp",
        command=[".venv/bin/python", "-m", "mcp_servers.compensation"],
        cwd=ROOT,
        port_env="COMPENSATION_MCP_PORT",
        default_port=8104,
        required_path=ROOT / "mcp_servers" / "compensation" / "__main__.py",
    ),
    "analytics-mcp": Service(
        name="analytics-mcp",
        command=[".venv/bin/python", "mcp_servers/analytics_mcp/main.py"],
        cwd=ROOT,
        port_env="ANALYTICS_MCP_PORT",
        default_port=8105,
        required_path=ROOT / "mcp_servers" / "analytics_mcp" / "main.py",
    ),
    "simulation-mcp": Service(
        name="simulation-mcp",
        command=[".venv/bin/python", "mcp_servers/simulation_mcp/main.py"],
        cwd=ROOT,
        port_env="SIMULATION_MCP_PORT",
        default_port=8106,
        required_path=ROOT / "mcp_servers" / "simulation_mcp" / "main.py",
    ),
}


def load_env_file() -> dict[str, str]:
    env = os.environ.copy()
    env_file = ROOT / ".env"
    if not env_file.exists():
        return env

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def resolve_port(service: Service, env: dict[str, str]) -> int | None:
    if service.port_env is None:
        return None
    value = env.get(service.port_env)
    return int(value) if value else service.default_port


def is_port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def render_command(service: Service, env: dict[str, str]) -> list[str]:
    port = resolve_port(service, env)
    return [part.format(port=port) for part in service.command]


def validate_services(names: list[str], env: dict[str, str]) -> None:
    for name in names:
        service = SERVICES[name]
        if service.required_path and not service.required_path.exists():
            missing_path = service.required_path.relative_to(ROOT)
            raise SystemExit(f"{name} cannot start; missing {missing_path}")
        port = resolve_port(service, env)
        if port is not None and is_port_busy(port):
            raise SystemExit(f"{name} cannot start; port {port} is already in use")


def start_service(service: Service, env: dict[str, str]) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{service.name}.log"
    log_file = log_path.open("a", encoding="utf-8")
    command = render_command(service, env)
    print(f"starting {service.name}; log={log_path}")
    return subprocess.Popen(
        command,
        cwd=service.cwd,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ProcessTwin native development services.")
    parser.add_argument(
        "--services",
        nargs="+",
        choices=sorted(SERVICES),
        default=["backend", "frontend", "celery"],
        help="Services to start.",
    )
    parser.add_argument("--backend-port", type=int, help="Override BACKEND_PORT for this run.")
    parser.add_argument("--frontend-port", type=int, help="Override FRONTEND_PORT for this run.")
    parser.add_argument(
        "--api-base-url",
        help="Override VITE_API_BASE_URL passed to the frontend process.",
    )
    parser.add_argument("--health", action="store_true", help="Run native service health checks.")
    return parser.parse_args()


def apply_cli_overrides(args: argparse.Namespace, env: dict[str, str]) -> None:
    if args.backend_port is not None:
        env["BACKEND_PORT"] = str(args.backend_port)
    if args.frontend_port is not None:
        env["FRONTEND_PORT"] = str(args.frontend_port)

    backend_port = env.get("BACKEND_PORT", "8000")
    if args.api_base_url:
        env["VITE_API_BASE_URL"] = args.api_base_url
    elif args.backend_port is not None or not env.get("VITE_API_BASE_URL"):
        env["VITE_API_BASE_URL"] = f"http://127.0.0.1:{backend_port}"


def main() -> int:
    args = parse_args()
    env = load_env_file()
    apply_cli_overrides(args, env)

    if args.health:
        return subprocess.call(
            [sys.executable, str(ROOT / "scripts" / "check_native.py")],
            cwd=ROOT,
            env=env,
        )

    validate_services(args.services, env)
    processes = [start_service(SERVICES[name], env) for name in args.services]

    try:
        while True:
            for name, process in zip(args.services, processes, strict=True):
                code = process.poll()
                if code is not None:
                    print(f"{name} exited with code {code}")
                    stop_processes(processes)
                    return code
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopping services")
        stop_processes(processes)
        return 0


if __name__ == "__main__":
    sys.exit(main())
