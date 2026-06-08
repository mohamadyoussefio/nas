#!/usr/bin/env python3
"""Shared helpers for intent rendering and device deployment."""

from __future__ import annotations

import ipaddress
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

try:
    from netmiko import ConnectHandler, file_transfer
except ImportError:  # pragma: no cover - optional for render-only mode
    ConnectHandler = None
    file_transfer = None


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output" / "configs"


@dataclass
class IPv4Details:
    cidr: str
    ip: str
    mask: str
    network: str


def parse_ipv4(cidr: str) -> IPv4Details:
    iface = ipaddress.ip_interface(cidr)
    return IPv4Details(
        cidr=cidr,
        ip=str(iface.ip),
        mask=str(iface.network.netmask),
        network=str(iface.network.network_address),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_context(intent: dict[str, Any]) -> dict[str, Any]:
    context = deepcopy(intent)
    devices = context["devices"]
    provider = context["provider"]

    pe_loopbacks = [
        {"name": n, "ip": str(ipaddress.ip_interface(d["loopback0"]).ip)}
        for n, d in devices.items()
        if d["role"] == "pe"
    ]

    for name, device in devices.items():
        _initialize_device_context(name, device, provider, pe_loopbacks)

    _process_customer_intent(context)

    _apply_global_te_policies(context)

    for _, device in devices.items():
        if device["role"] == "pe":
            device["vrfs"] = sorted(device["vrfs"], key=lambda item: item["name"])

    return context


def _initialize_device_context(name: str, device: dict[str, Any], provider: dict[str, Any], pe_loopbacks: list[dict[str, str]]) -> None:
    device["name"] = name
    device["loopback0"] = _iface_to_dict(device["loopback0"])
    device["interfaces"] = [_normalize_interface(iface) for iface in device.get("interfaces", [])]
    device["vrfs"] = []
    device["ibgp_neighbors"] = []
    device["prefix_lists"] = []
    device["route_maps"] = []
    device["advertised_networks"] = []
    device["te_tunnels"] = []

    if device["role"] == "pe":
        device["ibgp_neighbors"] = [
            {"name": peer["name"], "ip": peer["ip"], "state": "present"}
            for peer in pe_loopbacks
            if peer["name"] != name
        ]
        for tunnel in provider.get("traffic_engineering", {}).get("tunnels", []):
            if tunnel["device"] == name:
                device["te_tunnels"].append(deepcopy(tunnel))

    if device["role"] == "ce":
        _normalize_ce_bgp(device)


def _normalize_ce_bgp(device: dict[str, Any]) -> None:
    bgp = device.get("bgp", {})
    if "neighbors" not in bgp and "neighbor_ip" in bgp:
        bgp["neighbors"] = [{"ip": bgp["neighbor_ip"], "asn": bgp["neighbor_asn"]}]
    
    normalized_neighbors = []
    for neighbor in bgp.get("neighbors", []):
        neighbor["state"] = neighbor.get("state", "present")
        neighbor["route_map_out"] = neighbor.get("route_map_out")
        
        # Support customer-driven Ingress TE via AS-Path prepending
        if neighbor.get("prepend_as_count"):
            policy_name = f"RM_PREPEND_OUT"
            neighbor["route_map_out"] = policy_name
            _ensure_ce_prepend_policy(device, policy_name, neighbor["prepend_as_count"])
            
        normalized_neighbors.append(neighbor)
    
    bgp["neighbors"] = normalized_neighbors
    device["bgp"] = bgp
    
    for iface in device["interfaces"]:
        if iface.get("state") == "absent":
            continue
        if iface.get("advertise"):
            network = ipaddress.ip_interface(iface["ipv4"]).network
            device["advertised_networks"].append(
                {
                    "network": str(network.network_address),
                    "mask": str(network.netmask),
                }
            )


def _process_customer_intent(context: dict[str, Any]) -> None:
    customers = context.get("customers", {})
    provider = context["provider"]
    devices = context["devices"]

    for _, customer in customers.items():
        vrf_source = customer["vrf"]
        vrf_name = vrf_source["name"]
        customer_asn = customer["asn"]

        for site in customer.get("sites", []):
            pe_device = devices[site["pe"]]
            ce_device = devices[site["ce"]]

            pe_iface = _find_interface_by_peer_network(pe_device["interfaces"], site["pe_ce_link"])
            ce_iface = _find_interface_by_peer_network(ce_device["interfaces"], site["pe_ce_link"])

            pe_vrf = _get_or_create_vrf(pe_device, vrf_name, vrf_source)
            
            # Ingress TE: If role is backup, set lower Local-Pref
            policy_in = site.get("policy_in")
            if site.get("role") == "backup":
                policy_name = f"RM_BACKUP_{ce_device['hostname']}"
                policy_in = policy_name
                _ensure_backup_route_map(pe_device, policy_name)

            pe_vrf["ce_neighbors"].append(
                {
                    "ip": ce_iface["ip"],
                    "asn": customer_asn,
                    "route_map_in": policy_in,
                    "route_map_out": site.get("policy_out"),
                    "state": "present",
                }
            )

            if customer.get("internet_access"):
                _leak_internet_vrf(pe_device, pe_vrf, provider)

            if "bgp" not in ce_device:
                ce_device["bgp"] = {"neighbors": []}
            
            # Add neighbor to CE if not already present
            if not any(n["ip"] == pe_iface["ip"] for n in ce_device["bgp"]["neighbors"]):
                ce_device["bgp"]["neighbors"].append({
                    "ip": pe_iface["ip"], 
                    "asn": provider["asn"],
                    "state": "present",
                    "route_map_out": None,
                })


def _ensure_backup_route_map(device: dict[str, Any], name: str) -> None:
    # Check if already exists
    if any(rm["name"] == name for rm in device["route_maps"]):
        return
    
    device["route_maps"].append(
        {
            "name": name,
            "sequence": 10,
            "match_prefix_list": None,
            "set_local_preference": 50,  # Lower than default 100
            "set_med": None,
            "set_as_path_prepend": None,
        }
    )


def _ensure_ce_prepend_policy(device: dict[str, Any], name: str, count: int) -> None:
    # Check if already exists
    if any(rm["name"] == name for rm in device["route_maps"]):
        return
    
    # Prepend the CE's own AS 'count' times
    prepend_string = " ".join([str(device["asn"])] * count)
    
    device["route_maps"].append(
        {
            "name": name,
            "sequence": 10,
            "match_prefix_list": None,
            "set_local_preference": None,
            "set_as_path_prepend": prepend_string,
            "set_med": None,
        }
    )


def _leak_internet_vrf(pe_device: dict[str, Any], customer_vrf: dict[str, Any], provider: dict[str, Any]) -> None:
    internet_vrf_source = provider.get("internet_vrf")
    if not internet_vrf_source:
        return

    # Leak Internet export RT into customer import list
    for rt in internet_vrf_source.get("export_rts", []):
        if rt not in customer_vrf["import_rts"]:
            customer_vrf["import_rts"].append(rt)

    # Ensure Internet VRF is instantiated on this PE
    _get_or_create_vrf(pe_device, internet_vrf_source["name"], internet_vrf_source)


def _iface_to_dict(cidr: str) -> dict[str, str]:
    parsed = parse_ipv4(cidr)
    return {
        "cidr": parsed.cidr,
        "ip": parsed.ip,
        "mask": parsed.mask,
        "network": parsed.network,
    }


def _normalize_interface(interface: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(interface)
    normalized["state"] = interface.get("state", "present")
    
    if normalized["state"] == "absent":
        return normalized

    parsed = parse_ipv4(interface["ipv4"])
    normalized["cidr"] = parsed.cidr
    normalized["ip"] = parsed.ip
    normalized["mask"] = parsed.mask
    normalized["network"] = parsed.network
    normalized["ospf"] = bool(interface.get("ospf", False))
    normalized["mpls"] = bool(interface.get("mpls", False))
    normalized["rsvp"] = bool(interface.get("rsvp", False))
    normalized["vrf"] = interface.get("vrf")
    normalized["advertise"] = bool(interface.get("advertise", False))
    return normalized


def _find_interface_by_peer_network(interfaces: list[dict[str, Any]], cidr: str) -> dict[str, Any]:
    target = str(ipaddress.ip_network(cidr, strict=False).network_address)
    for interface in interfaces:
        if interface["network"] == target:
            return interface
    raise ValueError(f"No interface found for PE-CE link {cidr}")


def _get_or_create_vrf(device: dict[str, Any], vrf_name: str, vrf_source: dict[str, Any]) -> dict[str, Any]:
    for vrf in device["vrfs"]:
        if vrf["name"] == vrf_name:
            return vrf

    vrf = {
        "name": vrf_source["name"],
        "rd": vrf_source["rd"],
        "import_rts": vrf_source.get("import_rts", []),
        "export_rts": vrf_source.get("export_rts", []),
        "ce_neighbors": [],
        "state": vrf_source.get("state", "present")
    }
    device["vrfs"].append(vrf)
    return vrf


def _apply_global_te_policies(context: dict[str, Any]) -> None:
    devices = context["devices"]
    for policy in context.get("traffic_engineering", {}).get("policies", []):
        device = devices[policy["device"]]
        device["prefix_lists"].append(
            {
                "name": policy["prefix_list_name"],
                "seq": policy.get("sequence", 10),
                "prefix": policy["prefix"],
            }
        )
        device["route_maps"].append(
            {
                "name": policy["route_map_name"],
                "sequence": policy.get("sequence", 10),
                "match_prefix_list": policy["prefix_list_name"],
                "set_local_preference": policy.get("set_local_preference"),
                "set_med": policy.get("set_med"),
                "set_as_path_prepend": None,
            }
        )


def validate_intent(intent: dict[str, Any]) -> None:
    devices = intent.get("devices", {})
    if not devices:
        raise ValueError("Intent must define devices")

    for name, device in devices.items():
        role = device.get("role")
        if role not in {"pe", "p", "ce"}:
            raise ValueError(f"Unsupported role for {name}: {role}")

        parse_ipv4(device["loopback0"])
        for interface in device.get("interfaces", []):
            if interface.get("state") != "absent":
                parse_ipv4(interface["ipv4"])

        if role == "ce":
            _validate_ce_bgp(device)

    _check_duplicate_ips(devices)
    _validate_phase4_requirements(intent)
    validate_gns3_intent(intent)


def _validate_ce_bgp(device: dict[str, Any]) -> None:
    bgp = device.get("bgp", {})
    if "neighbors" in bgp:
        for neighbor in bgp["neighbors"]:
            ipaddress.ip_address(neighbor["ip"])


def _validate_phase4_requirements(intent: dict[str, Any]) -> None:
    provider = intent.get("provider", {})
    customers = intent.get("customers", {})

    for name, cust in customers.items():
        if cust.get("internet_access") and "internet_vrf" not in provider:
            raise ValueError(f"Customer {name} requested internet_access but 'provider.internet_vrf' is missing")


def validate_gns3_intent(intent: dict[str, Any]) -> None:
    gns3 = intent.get("gns3")
    if not gns3:
        return

    if "project_name" not in gns3:
        raise ValueError("gns3.project_name is required when the gns3 section is present")

    templates = gns3.get("templates", {})
    nodes = gns3.get("nodes", {})
    links = gns3.get("links", [])
    devices = intent["devices"]

    for device_name in devices:
        if device_name not in nodes:
            raise ValueError(f"gns3.nodes is missing placement data for {device_name}")
        template_alias = nodes[device_name].get("template")
        if template_alias and template_alias not in templates:
            raise ValueError(f"gns3 template alias '{template_alias}' for {device_name} is not defined")

    for link in links:
        endpoints = link.get("endpoints", [])
        if len(endpoints) != 2:
            raise ValueError("Each gns3 link must define exactly 2 endpoints")
        for endpoint in endpoints:
            node_name = endpoint["device"]
            if node_name not in devices:
                raise ValueError(f"GNS3 link references unknown device {node_name}")


def _check_duplicate_ips(devices: dict[str, Any]) -> None:
    seen: dict[str, str] = {}
    for name, device in devices.items():
        # Get all interfaces except those being deleted
        # Note: at validation stage, loopback0 is still a raw CIDR string
        ifaces = [{"name": "loopback0", "ipv4": device["loopback0"]}] + \
                 [iface for iface in device.get("interfaces", []) if iface.get("state") != "absent"]
        
        for iface in ifaces:
            ip = str(ipaddress.ip_interface(iface["ipv4"]).ip)
            owner = seen.get(ip)
            
            # Allow duplicates ONLY if it's a Loopback (Anycast scenario)
            is_loopback = "loopback" in iface.get("name", "").lower()
            if owner and not is_loopback:
                raise ValueError(f"Duplicate IP {ip} on {owner} and {name}")
            
            if not owner:
                seen[ip] = name


def render_configs(context: dict[str, Any]) -> dict[str, str]:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("device_config.j2")
    rendered = {}

    for name, device in context["devices"].items():
        rendered[name] = template.render(device=device, provider=context["provider"]).strip() + "\n"

    return rendered


def write_configs(rendered: dict[str, str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, config in rendered.items():
        path = OUTPUT_DIR / f"{name}.cfg"
        path.write_text(config, encoding="utf-8")


def deploy_configs_replace(context: dict[str, Any], rendered: dict[str, str]) -> None:
    """Deploy configs using SCP and 'configure replace' for true idempotency."""
    defaults = context.get("defaults", {})

    for name, device in context["devices"].items():
        if "mgmt_ip" not in device:
            print(f"Skipping {name}: missing mgmt_ip")
            continue

        connection = {
            "device_type": device.get("device_type", defaults.get("device_type", "cisco_ios")),
            "host": device["mgmt_ip"],
            "username": device.get("mgmt_username", defaults.get("mgmt_username", "admin")),
            "password": device.get("mgmt_password", defaults.get("mgmt_password", "admin")),
        }

        filename = f"{name}.cfg"
        source_file = OUTPUT_DIR / filename
        # Ensure the file exists on disk
        source_file.write_text(rendered[name], encoding="utf-8")

        print(f"[{name}] Starting declarative deployment (Configure Replace)...")
        with ConnectHandler(**connection) as net_connect:
            # Transfer the file via SCP
            print(f"[{name}] Transferring {filename} to flash...")
            file_transfer(
                net_connect,
                source_file=str(source_file),
                dest_file=filename,
                file_system="flash:",  # Adjust if your GNS3 image uses disk0:
                direction="put",
                overwrite_file=True,
            )

            # Apply the configuration replace
            print(f"[{name}] Executing 'configure replace'...")
            # 'force' avoids the confirmation prompt
            output = net_connect.send_command(
                f"configure replace flash:{filename} force",
                expect_string=r"#",
                read_timeout=120,
            )
            print(output)
            print(f"[{name}] Deployment complete.")


def deploy_configs(context: dict[str, Any], rendered: dict[str, str]) -> None:
    if ConnectHandler is None:
        raise RuntimeError("Netmiko is not installed. Install dependencies before using --deploy.")

    defaults = context.get("defaults", {})

    for name, device in context["devices"].items():
        if "mgmt_ip" not in device:
            raise ValueError(f"Device {name} is missing mgmt_ip required for deployment")

        connection = {
            "device_type": device.get("device_type", defaults.get("device_type", "cisco_ios")),
            "host": device["mgmt_ip"],
            "username": device.get("mgmt_username", defaults.get("mgmt_username")),
            "password": device.get("mgmt_password", defaults.get("mgmt_password")),
        }

        print(f"Deploying config to {name} ({device['mgmt_ip']})")
        with ConnectHandler(**connection) as net_connect:
            output = net_connect.send_config_set(rendered[name].splitlines())
            print(output)
            net_connect.save_config()
