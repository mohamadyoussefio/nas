#!/usr/bin/env python3
"""Create a GNS3 topology from intent, start it, and optionally deploy configs."""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path
from typing import Any

import requests # type: ignore

from automation_lib import build_context, deploy_configs, load_yaml, render_configs, validate_intent, write_configs


class GNS3Client:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.timeout = timeout

    def get(self, path: str) -> Any:
        response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: Any | None = None, raw: str | None = None) -> Any:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if raw is not None:
            kwargs["data"] = raw.encode("utf-8")
            kwargs["headers"] = {"Content-Type": "application/octet-stream"}
        elif payload is not None:
            kwargs["json"] = payload
        response = self.session.post(f"{self.base_url}{path}", **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text.strip()
            detail = f" Response body: {body}" if body else ""
            raise requests.HTTPError(f"{exc}.{detail}", response=response) from exc
        if response.content:
            return response.json()
        return None

    def delete(self, path: str) -> None:
        response = self.session.delete(f"{self.base_url}{path}", timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text.strip()
            detail = f" Response body: {body}" if body else ""
            raise requests.HTTPError(f"{exc}.{detail}", response=response) from exc


def ensure_project(client: GNS3Client, project_name: str) -> dict[str, Any]:
    for project in client.get("/v2/projects"):
        if project["name"] == project_name:
            return project
    return client.post("/v2/projects", {"name": project_name})


def reset_project(client: GNS3Client, project_name: str) -> None:
    for project in client.get("/v2/projects"):
        if project["name"] == project_name:
            client.delete(f"/v2/projects/{project['project_id']}")
            print(f"Deleted existing GNS3 project: {project_name}")
            return


def get_templates_by_name(client: GNS3Client) -> dict[str, dict[str, Any]]:
    return {template["name"]: template for template in client.get("/v2/templates")}


def get_existing_nodes(client: GNS3Client, project_id: str) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in client.get(f"/v2/projects/{project_id}/nodes")}


def ensure_nodes(
    client: GNS3Client,
    project_id: str,
    gns3: dict[str, Any],
    templates: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    existing = get_existing_nodes(client, project_id)
    created = dict(existing)

    for device_name, node_data in gns3["nodes"].items():
        if device_name in created:
            continue

        template_alias = node_data["template"]
        template_name = gns3["templates"][template_alias]["name"]
        if template_name not in templates:
            raise ValueError(
                f"GNS3 template '{template_name}' referenced by alias '{template_alias}' does not exist on the controller"
            )

        template = templates[template_name]
        payload = {
            "compute_id": node_data.get("compute_id", gns3.get("compute_id", template.get("compute_id", "local"))),
            "name": device_name,
            "x": node_data["x"],
            "y": node_data["y"],
        }
        created[device_name] = client.post(f"/v2/projects/{project_id}/templates/{template['template_id']}", payload)

    return created


def ensure_links(client: GNS3Client, project_id: str, nodes: dict[str, dict[str, Any]], gns3: dict[str, Any]) -> None:
    existing_links = client.get(f"/v2/projects/{project_id}/links")
    existing_signatures = {_link_signature(link, nodes_by_id={node["node_id"]: name for name, node in nodes.items()}) for link in existing_links}
    used_ports = {
        (nodes_by_id[endpoint["node_id"]], endpoint["adapter_number"], endpoint["port_number"])
        for link in existing_links
        for endpoint in link["nodes"]
        for nodes_by_id in [{node["node_id"]: name for name, node in nodes.items()}]
    }

    for link in gns3.get("links", []):
        signature = _intent_link_signature(link)
        if signature in existing_signatures:
            continue
        if any((endpoint["device"], endpoint["adapter_number"], endpoint["port_number"]) in used_ports for endpoint in link["endpoints"]):
            print(f"Skipping link {signature} because one of its ports is already in use")
            continue

        endpoints = []
        for endpoint in link["endpoints"]:
            node = nodes[endpoint["device"]]
            _validate_node_port(endpoint["device"], node, endpoint["adapter_number"], endpoint["port_number"])
            endpoints.append(
                {
                    "node_id": node["node_id"],
                    "adapter_number": endpoint["adapter_number"],
                    "port_number": endpoint["port_number"],
                }
            )
        client.post(f"/v2/projects/{project_id}/links", {"nodes": endpoints})
        used_ports.update(
            (endpoint["device"], endpoint["adapter_number"], endpoint["port_number"])
            for endpoint in link["endpoints"]
        )


def _validate_node_port(device_name: str, node: dict[str, Any], adapter_number: int, port_number: int) -> None:
    ports = node.get("ports", [])
    for port in ports:
        if port.get("adapter_number") == adapter_number and port.get("port_number") == port_number:
            return

    available = sorted((port.get("adapter_number"), port.get("port_number")) for port in ports)
    raise ValueError(
        f"Node {device_name} does not expose port {adapter_number}/{port_number}. "
        f"Available ports: {available}"
    )


def _link_signature(link: dict[str, Any], nodes_by_id: dict[str, str]) -> tuple[tuple[str, int, int], tuple[str, int, int]]:
    endpoints = []
    for endpoint in link["nodes"]:
        endpoints.append(
            (
                nodes_by_id[endpoint["node_id"]],
                endpoint["adapter_number"],
                endpoint["port_number"],
            )
        )
    return tuple(sorted(endpoints))


def _intent_link_signature(link: dict[str, Any]) -> tuple[tuple[str, int, int], tuple[str, int, int]]:
    endpoints = []
    for endpoint in link["endpoints"]:
        endpoints.append((endpoint["device"], endpoint["adapter_number"], endpoint["port_number"]))
    return tuple(sorted(endpoints))


def start_nodes(client: GNS3Client, project_id: str) -> None:
    client.post(f"/v2/projects/{project_id}/nodes/start")


class TelnetConsoleClient:
    IAC = 255
    DONT = 254
    DO = 253
    WONT = 252
    WILL = 251

    def __init__(self, host: str, port: int, timeout: int = 5) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def __enter__(self) -> "TelnetConsoleClient":
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.sock:
            self.sock.close()

    def _recv_processed(self, timeout: float = 1.0) -> str:
        if not self.sock:
            return ""
        self.sock.settimeout(timeout)
        chunks = bytearray()
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            chunks.extend(self._process_telnet_bytes(data))
        return chunks.decode("utf-8", errors="ignore")

    def _process_telnet_bytes(self, data: bytes) -> bytes:
        if not self.sock:
            return b""
        output = bytearray()
        idx = 0
        while idx < len(data):
            byte = data[idx]
            if byte == self.IAC and idx + 1 < len(data):
                cmd = data[idx + 1]
                if cmd == self.IAC:
                    output.append(self.IAC)
                    idx += 2
                    continue
                if idx + 2 < len(data):
                    opt = data[idx + 2]
                    if cmd in (self.DO, self.DONT):
                        self.sock.sendall(bytes([self.IAC, self.WONT, opt]))
                    elif cmd in (self.WILL, self.WONT):
                        self.sock.sendall(bytes([self.IAC, self.DONT, opt]))
                    idx += 3
                    continue
            output.append(byte)
            idx += 1
        return bytes(output)

    def send_line(self, line: str = "") -> None:
        if not self.sock:
            return
        self.sock.sendall((line + "\r\n").encode("utf-8"))

    def wait_for_prompt(self, prompts: tuple[str, ...], wait_seconds: float = 8.0) -> str:
        deadline = time.time() + wait_seconds
        output = ""
        while time.time() < deadline:
            output += self._recv_processed(timeout=0.5)
            lowered = output.lower()
            if "initial configuration dialog" in lowered:
                self.send_line("no")
            if "would you like to terminate autoinstall" in lowered:
                self.send_line("yes")
            if "[confirm]" in output or "overwrite the previous nvram configuration?" in lowered:
                self.send_line("")
                output = ""
                continue
            if any(prompt in output for prompt in prompts):
                return output
        raise TimeoutError(f"Did not receive prompt {prompts} from console {self.host}:{self.port}. Last output: {output[-400:]}")

    def expect_ready(self, wait_seconds: int = 120) -> None:
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            self.send_line("")
            output = self._recv_processed(timeout=2.0)
            lowered = output.lower()
            if "initial configuration dialog" in lowered:
                self.send_line("no")
                continue
            if "press return to get started" in lowered:
                self.send_line("")
                continue
            if "would you like to terminate autoinstall" in lowered:
                self.send_line("yes")
                continue
            if "router>" in lowered or "router#" in lowered or "router(config" in lowered:
                return
            if ">" in output or "#" in output:
                return
            time.sleep(2)
        raise TimeoutError(f"Console {self.host}:{self.port} did not become ready in {wait_seconds} seconds")

    def run_commands(self, commands: list[str], save_config: bool = True) -> None:
        self.send_line("")
        self.wait_for_prompt((">", "#"), wait_seconds=5.0)
        self.send_line("enable")
        self.wait_for_prompt(("#",), wait_seconds=5.0)
        self.send_line("terminal length 0")
        self.wait_for_prompt(("#",), wait_seconds=5.0)
        self.send_line("configure terminal")
        self.wait_for_prompt(("(config)#",), wait_seconds=5.0)
        for command in commands:
            if not command or command == "end":
                continue
            self.send_line(command)
            if command == "!":
                continue
            if command.startswith("interface "):
                self.wait_for_prompt(("(config-if)#", "(config)#"), wait_seconds=5.0)
            elif command.startswith("router "):
                self.wait_for_prompt(("(config-router)#", "(config)#"), wait_seconds=5.0)
            elif command.startswith("address-family "):
                self.wait_for_prompt(("(config-router-af)#", "(config)#", "(config-router)#"), wait_seconds=5.0)
            else:
                self.wait_for_prompt(("(config", "#"), wait_seconds=5.0)
        self.send_line("end")
        self.wait_for_prompt(("#",), wait_seconds=5.0)
        if save_config:
            self.send_line("write memory")
            self.wait_for_prompt(("#", "[ok]"), wait_seconds=15.0)


def deploy_configs_via_gns3_console(
    client: GNS3Client,
    project_id: str,
    rendered: dict[str, str],
    wait_seconds: int = 180,
) -> None:
    nodes = get_existing_nodes(client, project_id)
    for name, config in rendered.items():
        if name not in nodes:
            raise ValueError(f"Device {name} does not exist in project {project_id}")
        node = nodes[name]
        console_host = node.get("console_host") or "127.0.0.1"
        console_port = node.get("console")
        if console_port is None:
            raise ValueError(f"Device {name} does not expose a console port in GNS3")
        print(f"Deploying config to {name} via GNS3 console {console_host}:{console_port}")
        commands = [line for line in config.splitlines() if line and line != "end"]
        with TelnetConsoleClient(console_host, int(console_port)) as console:
            console.expect_ready(wait_seconds=wait_seconds)
            console.run_commands(commands)


def wait_after_boot(seconds: int) -> None:
    if seconds > 0:
        print(f"Waiting {seconds} seconds for nodes to boot")
        time.sleep(seconds)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True, type=Path, help="Path to the YAML intent file")
    parser.add_argument("--write-files", action="store_true", help="Write rendered configs to output/configs")
    parser.add_argument("--create", action="store_true", help="Create or reuse the GNS3 project, nodes, and links")
    parser.add_argument("--start", action="store_true", help="Start all nodes in the GNS3 project")
    parser.add_argument("--deploy", action="store_true", help="Deploy configs after rendering")
    parser.add_argument("--reset-project", action="store_true", help="Delete any existing GNS3 project with the same name before recreating it")
    parser.add_argument(
        "--deploy-method",
        choices=("gns3-console", "netmiko"),
        default="gns3-console",
        help="How to deploy configs when using --deploy",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    intent = load_yaml(args.intent)
    validate_intent(intent)
    context = build_context(intent)
    rendered = render_configs(context)

    if args.write_files:
        write_configs(rendered)
        print("Rendered configs written to output/configs")

    project_id: str | None = None
    client: GNS3Client | None = None
    gns3 = intent.get("gns3")

    if args.create or args.start or args.reset_project or (args.deploy and args.deploy_method == "gns3-console"):
        if not gns3:
            raise ValueError("The intent file must include a gns3 section when using --create, --start, or --deploy-method gns3-console")
        client = GNS3Client(gns3.get("controller_url", "http://127.0.0.1:3080"))
        if args.reset_project:
            reset_project(client, gns3["project_name"])
        project = ensure_project(client, gns3["project_name"])
        project_id = project["project_id"]
        print(f"GNS3 project ready: {gns3['project_name']} ({project_id})")

        if args.create:
            templates = get_templates_by_name(client)
            nodes = ensure_nodes(client, project_id, gns3, templates)
            ensure_links(client, project_id, nodes, gns3)
            print(f"Topology synchronized for {len(nodes)} nodes")

        if args.start:
            start_nodes(client, project_id)
            wait_after_boot(gns3.get("boot_wait_seconds", 120))
            print("Topology started")

    if args.deploy:
        if args.deploy_method == "gns3-console":
            if not client or not project_id:
                raise ValueError("GNS3 project context is required for console deployment")
            deploy_configs_via_gns3_console(
                client,
                project_id,
                rendered,
                wait_seconds=gns3.get("console_wait_seconds", 120) if gns3 else 120,
            )
        else:
            deploy_configs(context, rendered)

    if not args.write_files and not args.create and not args.start and not args.deploy:
        for name, config in rendered.items():
            print(f"\n===== {name} =====")
            print(config)


if __name__ == "__main__":
    main()
