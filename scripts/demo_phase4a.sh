#!/bin/bash

# Professional Phase 4.a Demo Script
# Objective: Demonstrate Add, Update, and Delete without manual editing.

set -e

# Colors for professional output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}   PHASE 4 DEMO: AUTOMATED CHANGE MANAGEMENT (MANAGEABILITY)  ${NC}"
echo -e "${BLUE}================================================================${NC}"
echo ""

# STEP 1: BASE STATE
echo -e "${GREEN}STEP 1: Establish Base State${NC}"
echo "Current Intent: Phase 4 Network (RSVP-TE + Internet VRF)"
echo "Action: Deploying clean base configuration..."
python3 scripts/build_lab.py --intent inventory/demo/1_base.yaml --deploy --deploy-method gns3-console
echo ""
echo -e "${BLUE}VERIFICATION:${NC} Run 'show ip interface brief' on CE1A. Loopback99 should NOT exist."
read -p "Press [Enter] to move to STEP 2 (ADD/UPDATE)..."

# STEP 2: ADD STATE
echo ""
echo -e "${GREEN}STEP 2: Automated Resource Provisioning (ADD)${NC}"
echo "Intent Change: Provisioning Loopback99 (9.9.9.9/32) on CE1A"
echo "Action: Deploying updated intent..."
python3 scripts/build_lab.py --intent inventory/demo/2_add.yaml --deploy --deploy-method gns3-console
echo ""
echo -e "${BLUE}VERIFICATION:${NC} Run 'show ip interface brief' on CE1A. Loopback99 is now PRESENT."
read -p "Press [Enter] to move to STEP 3 (DELETE)..."

# STEP 3: DELETE STATE
echo ""
echo -e "${GREEN}STEP 3: Automated Resource Decommissioning (DELETE)${NC}"
echo "Intent Change: Setting Loopback99 to 'state: absent'"
echo "Action: Deploying cleanup intent..."
python3 scripts/build_lab.py --intent inventory/demo/3_delete.yaml --deploy --deploy-method gns3-console
echo ""
echo -e "${BLUE}VERIFICATION:${NC} Run 'show ip interface brief' on CE1A. Loopback99 is cleanly GONE (No ghost configs)."
echo ""
echo -e "${BLUE}================================================================${NC}"
echo -e "${GREEN}   DEMO COMPLETE: INFRASTRUCTURE-AS-CODE PIPELINE VERIFIED      ${NC}"
echo -e "${BLUE}================================================================${NC}"
