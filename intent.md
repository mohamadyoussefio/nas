**System Role & Objective**
Act as a Senior Network Automation Engineer. Your task is to help me develop a Python-based automation tool to provision BGP/MPLS VPN services in a GNS3 environment. The tool must take a human-readable topology and service definition (e.g., YAML/JSON) and automatically generate and push configurations to Cisco IOS routers.

**Core Design Principles**

1. **Modularity:** Separate data models (YAML/JSON), configuration templates (Jinja2), and execution logic (Python).
2. 
**Idempotency & Manageability:** The tool must be able to add, delete, or update configurations without requiring a router reload, a full configuration wipe, or "config ghosting".


3. **Carrier-Grade Standards:** Ensure routing logic strictly adheres to service provider best practices (e.g., loopback-to-loopback BGP peering, proper VRF isolation).

**Project Phasing & Technical Requirements**
Please write the code and templates to support the following phased rollout:

**Phase 0: Core Setup**

* 
**Topology:** Base support for 4 core routers in a row (`PE1-P1-P2-PE2`).


* 
**Interfaces:** Automate the configuration of IPv4 interfaces and IPv4 Loopback Interfaces.


* 
**IGP:** Implement OSPF(v2) to route the loopbacks across the core. Ensure routing and forwarding can be validated.



**Phase 1: Core MPLS Routing**

* 
**LDP:** Enable and automate LDP configuration on core interfaces.


* 
**Validation:** The configuration must result in stable LDP session states and functional MPLS transport in the core, maintaining Penultimate Hop Popping (PHP) behavior.



**Phase 2: Core BGP/MPLS VPN Routing**

* 
**BGP Configuration:** Automate the setup of iBGP for the `vpnv4` address family.


* 
**Peering:** Establish iBGP sessions exclusively from Loopback to Loopback. Avoid using IS-IS; stick to OSPF as the IGP.



**Phase 3: Customer Onboarding (Edge)**

* 
**Edge Topology:** Add support for 4 CE (Customer Edge) routers representing 2 distinct customers.


* 
**VRF Provisioning:** Automate the creation of VRFs on the PE routers and associate these VRFs with the specific PE-CE interfaces.


* 
**PE-CE Routing:** Automate eBGP as the routing protocol between the PE and CE. This requires normal BGP configuration on the CE side and normal BGP configuration within the VRF on the PE side.


* 
**Validation:** Ensure networks attached to the CE are routable, routes appear in the correct tables, and there is strict isolation (no route leaking among customers).



**Phase 4: Advanced Services (To be built cleanly on top of previous phases)**

* 
**Site Sharing:** Include logic to allow site sharing among customers by manipulating Route Targets (multiple RTs).


* 
**Internet Services:** Add standard Internet services on the same core network, ensuring distinct customer interfaces are managed cleanly.


* 
**Traffic Engineering (TE):** Implement Ingress TE services for multi-connected CE routers. If a CE is connected to two PEs, provide a mechanism (e.g., BGP attribute manipulation like Local Preference or MED) so the customer can control inbound traffic paths for specific prefixes dynamically.


* 
**RSVP:** Add RSVP capabilities for traffic engineering.



**Deliverables Expected from You:**

1. A suggested project directory structure (e.g., separating `templates/`, `inventory/`, `scripts/`).
2. The foundational Python script using a library like `Netmiko` or `Nornir` to push configs.
3. The Jinja2 templates required for Phase 0 and Phase 1 to get the core backbone running.
4. An example YAML "Intent" file that a user would fill out to define their topology.