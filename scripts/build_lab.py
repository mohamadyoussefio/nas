#!/usr/bin/env python3
"""Create a GNS3 topology from intent, start it, and optionally deploy configs."""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path
from typing import Any

import requests
from automation_lib import build_context, load_yaml, render_configs, validate_intent, write_configs


class GNS3Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, json: Any = None) -> Any:
        url = f"{self.base_url}/v2{path}"
        resp = requests.request(method, url, json=json)
        if resp.status_code >= 400:
            try:
                error = resp.json().get("message", resp.text)
            except Exception:
                error = resp.text
            raise RuntimeError(f"GNS3 API error ({resp.status_code}): {error}")
        return resp.json() if resp.text else None


class TelnetConsoleClient:
    def __init__(self, host: str, port: int, timeout: float = 120.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def __enter__(self) -> TelnetConsoleClient:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.sock:
            self.sock.close()

    def send_line(self, line: str) -> None:
        if not self.sock:
            raise RuntimeError("Console client not connected")
        self.sock.sendall(line.encode("ascii") + b"\r\n")

    def wait_for_prompt(self, prompts: tuple[str, ...], wait_seconds: float = 30.0) -> str:
        if not self.sock:
            raise RuntimeError("Console client not connected")
        start = time.time()
        output = ""
        while time.time() - start < wait_seconds:
            data = self.sock.recv(4096).decode("ascii", errors="ignore")
            output += data
            if any(p in output for p in prompts):
                return output
            time.sleep(0.5)
        raise TimeoutError(f"Did not receive prompt {prompts} from console {self.host}:{self.port}. Last output: {output[-400:]}")

    def expect_ready(self, wait_seconds: int = 300) -> None:
        start = time.time()
        while time.time() - start < wait_seconds:
            self.send_line("")
            try:
                output = self.wait_for_prompt((">", "#", "yes/no", "initial configuration dialog", "Username:", "Password:"), wait_seconds=10.0)
            except TimeoutError:
                continue
            lowered = output.lower()
            if "username:" in lowered:
                self.send_line("admin")
                continue
            if "password:" in lowered:
                self.send_line("admin")
                continue
            if "initial configuration dialog" in lowered or "[yes/no]" in lowered:
                self.send_line("no")
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
        # Get to a known state (Privileged EXEC)
        self.send_line("")
        output = self.wait_for_prompt((">", "#"), wait_seconds=60.0)
        if ">" in output:
            self.send_line("enable")
            self.wait_for_prompt(("#",), wait_seconds=10.0)
        
        self.send_line("terminal length 0")
        self.wait_for_prompt(("#",), wait_seconds=10.0)
        self.send_line("configure terminal")
        self.wait_for_prompt(("(config", "#"), wait_seconds=10.0)
        for command in commands:
            if not command or command.strip() == "!" or command == "end":
                continue
            self.send_line(command.strip())
            # For large configs, wait for each line to be processed
            time.sleep(0.1)
            self.wait_for_prompt(("#", ">"), wait_seconds=15.0)
        self.send_line("end")
        self.wait_for_prompt(("#",), wait_seconds=10.0)
        if save_config:
            self.send_line("write memory")
            self.wait_for_prompt(("#", "[ok]"), wait_seconds=60.0)


def get_existing_nodes(client: GNS3Client, project_id: str) -> dict[str, dict[str, Any]]:
    nodes = client.request("GET", f"/projects/{project_id}/nodes")
    return {n["name"]: n for n in nodes}


def ensure_project(client: GNS3Client, name: str) -> dict[str, Any]:
    projects = client.request("GET", "/projects")
    for p in projects:
        if p["name"] == name:
            return p
    return client.request("POST", "/projects", json={"name": name})


def reset_project(client: GNS3Client, name: str) -> None:
    projects = client.request("GET", "/projects")
    for p in projects:
        if p["name"] == name:
            client.request("DELETE", f"/projects/{p['project_id']}")
            print(f"Deleted existing GNS3 project: {name}")


def get_templates_by_name(client: GNS3Client) -> dict[str, dict[str, Any]]:
    templates = client.request("GET", "/templates")
    return {t["name"]: t for n, t in templates.items()} if isinstance(templates, dict) else {t["name"]: t for t in templates}


def ensure_nodes(client: GNS3Client, project_id: str, gns3_intent: dict[str, Any], templates: dict[str, dict[str, Any]]) -> dict[str, str]:
    existing = get_existing_nodes(client, project_id)
    node_name_to_id = {}

    for name, node_data in gns3_intent["nodes"].items():
        if name in existing:
            node_name_to_id[name] = existing[name]["node_id"]
            continue
        template_name = gns3_intent["templates"][node_data["template"]]["name"]
        template = templates.get(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found in GNS3")
        
        print(f"Creating node: {name} using template: {template_name}")
        node_type = template.get("node_type") or template.get("template_type")
        print(f"  Detected node type: {node_type}")
        payload = {
            "name": name,
            "node_type": node_type,
            "x": node_data["x"],
            "y": node_data["y"],
            "template_id": template["template_id"],
            "compute_id": gns3_intent.get("compute_id", "local"),
            "symbol": template.get("symbol")
        }

        # Dynamips nodes require specific properties to be nested
        if node_type == "dynamips":
            properties = {}
            dynamips_fields = {
                "platform", "nvram", "ram", "slot0", "slot1", "slot2", "slot3", 
                "idlepc", "idlesleep", "idlemax", "mmap", "sparsemem", 
                "midplane", "npe", "image", "system_id", "disk0", "disk1",
                "auto_delete_disks", "exec_area"
            }
            for field in dynamips_fields:
                if field in template:
                    properties[field] = template[field]
            payload["properties"] = properties
        
        node = client.request("POST", f"/projects/{project_id}/nodes", json=payload)
        
        # Ensure the name is exactly what we requested (GNS3 sometimes defaults to R1, R2...)
        if node.get("name") != name:
            print(f"Node created as {node.get('name')}, renaming to {name}...")
            node = client.request("PUT", f"/projects/{project_id}/nodes/{node['node_id']}", json={"name": name})
            
        node_name_to_id[name] = node["node_id"]

    return node_name_to_id


def ensure_links(client: GNS3Client, project_id: str, nodes: dict[str, str], gns3_intent: dict[str, Any]) -> None:
    existing_links = client.request("GET", f"/projects/{project_id}/links")
    for link_data in gns3_intent.get("links", []):
        endpoints = link_data["endpoints"]
        node_a_id = nodes[endpoints[0]["device"]]
        node_b_id = nodes[endpoints[1]["device"]]
        
        link_exists = False
        for ex in existing_links:
            e = ex["nodes"]
            if {e[0]["node_id"], e[1]["node_id"]} == {node_a_id, node_b_id}:
                link_exists = True
                break
        if not link_exists:
            print(f"Connecting {endpoints[0]['device']} to {endpoints[1]['device']}...")
            client.request("POST", f"/projects/{project_id}/links", json={
                "nodes": [
                    {"node_id": node_a_id, "adapter_number": endpoints[0]["adapter_number"], "port_number": endpoints[0]["port_number"]},
                    {"node_id": node_b_id, "adapter_number": endpoints[1]["adapter_number"], "port_number": endpoints[1]["port_number"]}
                ]
            })
            time.sleep(0.2) # small delay to be safe


def start_nodes(client: GNS3Client, project_id: str) -> None:
    client.request("POST", f"/projects/{project_id}/nodes/start", json={})


def wait_after_boot(seconds: int) -> None:
    if seconds > 0:
        print(f"Waiting for nodes to stabilize...")
        for i in range(seconds, 0, -1):
            width = 40
            progress = int((seconds - i) / seconds * width)
            bar = "█" * progress + "░" * (width - progress)
            print(f"\r[{bar}] {i: >3}s remaining ", end="", flush=True)
            time.sleep(1)
        print(f"\r[{'█' * 40}] Boot sequence complete!   \n")


def deploy_configs_via_gns3_console(
    client: GNS3Client,
    project_id: str,
    rendered: dict[str, str],
    wait_seconds: int = 180,
) -> None:
    nodes = get_existing_nodes(client, project_id)
    total = len(rendered)
    print("Initializing deployment pipeline...")
    for i, (name, config) in enumerate(rendered.items(), 1):
        if name not in nodes:
            raise ValueError(f"Device {name} does not exist in project {project_id}")
        node = nodes[name]
        console_host = node.get("console_host") or "127.0.0.1"
        console_port = node.get("console")
        if console_port is None:
            raise ValueError(f"Device {name} does not expose a console port in GNS3")

        progress = int((i / total) * 20)
        bar = "█" * progress + "░" * (20 - progress)
        print(f"[{bar}] {i}/{total} | Provisioning: {name: <6}", end="\r", flush=True)
        
        commands = [line for line in config.splitlines() if line and line != "end"]
        with TelnetConsoleClient(console_host, int(console_port)) as console:
            console.expect_ready(wait_seconds=wait_seconds)
            console.run_commands(commands, save_config=True)
    
    print(f"\nFinalized deployment for all {total} infrastructure nodes.")


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
                raise RuntimeError("Client or project_id not initialized")
            deploy_configs_via_gns3_console(
                client,
                project_id,
                rendered,
                wait_seconds=gns3.get("console_wait_seconds", 120) if gns3 else 120,
            )
        else:
            from automation_lib import deploy_configs
            deploy_configs(context, rendered)


if __name__ == "__main__":
    main()
