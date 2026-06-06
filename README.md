# BGP/MPLS VPN Intent-Based Automation Framework

[![Infrastructure: GNS3](https://img.shields.io/badge/Infrastructure-GNS3-blue.svg)](https://www.gns3.com/)
[![Language: Python](https://img.shields.io/badge/Language-Python-yellow.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 1. Summary

This framework provides an enterprise-grade Model-Driven Automation solution for provisioning and managing Carrier-Grade BGP/MPLS VPN backbones. By utilizing an Infrastructure-as-Code (IaC) methodology, the system automates the entire network lifecycle—from initial topology synchronization to advanced Traffic Engineering and multi-tenant service delivery.

---

## 2. Design

The framework is built upon a modular Model-Template-Execution architecture to ensure scalability and maintainability.

### 2.1 The Data Model
The central source of truth resides in `inventory/intent.yaml`. This declarative model defines the desired state of the network, including core infrastructure (P/PE routers), customer edge (CE) nodes, VRF definitions, RSVP-TE tunnel parameters, and shared service policies.

### 2.2 Configuration Blueprints
Jinja2 templates located in `templates/device_config.j2` serve as the logical engine for generating vendor-specific configurations. These templates incorporate complex networking logic to transform abstract intent into syntactically correct Cisco IOS commands.

### 2.3 Orchestration Engine
The Python-based logic in `scripts/` handles the enrichment of the data model, performs rigorous IP integrity validation, and interacts with the GNS3 REST API to manage the virtual environment.

---

## 3. Prerequisites

Successful deployment requires the Cisco 7200 router appliance within the GNS3 environment.

*   **Appliance Download:** [Cisco 7200 Template](https://gns3.com/marketplace/appliances/cisco-7200)
*   **Documentation:** [Cisco 7200 Installation Tutorial](https://gns3.com/marketplace/appliances/cisco-7200)

### 3.1 Template Configuration Guidance

The following settings must be applied to the Cisco 7200 template to ensure full compatibility with the automation engine.

#### Figure 1: General Router Settings
![General Router Settings](assets/router_settings_general.png)

#### Figure 2: Memory and Disk Allocation
![Memory and Disk Allocation](assets/router_settings_memories_and_disk.png)

#### Figure 3: Interface Slot Configuration
![Interface Slot Configuration](assets/router_settings_slots.png)

---

## 4. Operational Quick Start

The system utilizes a unified `Makefile` to provide a simplified interface for complex orchestration tasks.

### 4.1 Environment Initialization
Prepare the Python virtual environment and install required dependencies:
```bash
make setup
```

### 4.2 Full System Deployment
Synchronize the GNS3 topology and deploy the comprehensive network configuration:
```bash
make build
```

### 4.3 Lifecycle Management Demonstration
Execute the automated demonstration of Add, Update, and Delete operations:
```bash
make demo
```

---

## 5. Project Implementation Phases

The project was developed through a rigorous engineering cycle consisting of six distinct phases:

| Phase | Scope | Technical Components |
| :--- | :--- | :--- |
| Phase 0 | Network Underlay | OSPFv2, Loopback addressing, P2P IP allocation |
| Phase 1 | MPLS Core | LDP Label Distribution, Label switching paths |
| Phase 2 | VPN Control Plane | Multi-protocol iBGP, VPNv4 Address Family |
| Phase 3 | Service Layer | VRF instantiation, eBGP PE-CE peering |
| Phase 4.a | Manageability | Declarative deletion logic (`state: absent`), State synchronization |
| Phase 4.b | Advanced Services | RSVP-TE, Shared Internet VRF, Ingress Path Steering |

---

## 6. Directory Structure

```text
├── inventory/      # Declarative Data Models
├── scripts/        # Automation & Orchestration Logic
├── templates/      # Jinja2 Configuration Blueprints
├── assets/         # Technical Figures and Visual Guides
├── output/         # Generated Production Configurations
└── Makefile        # System Command Interface
```

---
**Technical documentation developed for the 3TC(A) NAS Project.**
