# BGP/MPLS VPN Intent Automation

This repository contains a Python-based intent renderer and deployment helper for a Cisco IOS GNS3 lab that provisions:

- OSPF underlay
- MPLS LDP
- iBGP `vpnv4`
- PE VRFs
- PE-CE eBGP
- Multi-RT site sharing scaffolding
- Internet VRF scaffolding
- Basic inbound traffic-engineering policy knobs for dual-homed sites
- GNS3 topology creation and node placement through the GNS3 controller API

## Platform Model

The project is now modeled for Cisco IOS on Dynamips 7200 routers in GNS3.

The sample intent assumes you create these GNS3 templates first:

- `7200-P`: 2 FastEthernet ports
- `7200-PE`: 4 FastEthernet ports
- `7200-PE-BIG`: 5 or more FastEthernet ports
- `7200-CE`: 2 FastEthernet ports
- `7200-CE-DUAL`: 3 or more FastEthernet ports

A practical module layout is:

- `7200-P` and `7200-CE`: `C7200-IO-2FE`
- `7200-PE` and `7200-CE-DUAL`: `C7200-IO-2FE` plus one `PA-2FE-TX`
- `7200-PE-BIG`: `C7200-IO-2FE` plus two `PA-2FE-TX`

The rendered configs therefore use `FastEthernet` interface names rather than `GigabitEthernet`.

## Why these IP addresses?

The sample intent uses RFC1918 private address space with realistic service-provider-style conventions:

- `/32` loopbacks from `10.255.0.0/24`
- `/31` point-to-point links from `10.0.0.0/16`
- customer LANs from `172.16.0.0/12`

This is safe for labs and avoids hijacking publicly assigned address space.

## Layout

- `inventory/intent.yaml`: topology and service intent
- `scripts/render_and_deploy.py`: renderer and optional Netmiko deploy tool
- `scripts/build_lab.py`: GNS3 project/topology builder plus optional deploy flow
- `scripts/automation_lib.py`: shared render/validate/deploy helpers
- `templates/device_config.j2`: Cisco IOS configuration template
- `output/configs/`: rendered device configurations

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/render_and_deploy.py --intent inventory/intent.yaml --write-files
```

Rendered configs will be written to `output/configs/`.

To build the GNS3 topology from intent:

```bash
python3 scripts/build_lab.py --intent inventory/intent.yaml --write-files --create
```

To create, start, and then deploy configs through the GNS3 console:

```bash
python3 scripts/build_lab.py --intent inventory/intent.yaml --write-files --create --start --deploy
```

To push to devices:

```bash
python3 scripts/render_and_deploy.py --intent inventory/intent.yaml --write-files --deploy
```

## Notes

- The script defaults to rendering and validation first.
- `scripts/build_lab.py --deploy` defaults to GNS3 console deployment, so a separate management network is not required.
- `scripts/render_and_deploy.py --deploy` still uses Netmiko and therefore requires management IP reachability.
- The generated configuration is additive and structured by feature blocks to keep ongoing management predictable.
- GNS3 node creation requires matching template names to already exist on your GNS3 controller.
- The sample `gns3.templates` section is Dynamips-specific and expects the template names listed in the platform model above.
