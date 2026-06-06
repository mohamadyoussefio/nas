#!/bin/bash

# BGP/MPLS VPN Intent Automation - Setup Script
# Use this to prepare your environment from scratch.

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}   BGP/MPLS VPN INTENT AUTOMATION: GETTING STARTED              ${NC}"
echo -e "${BLUE}================================================================${NC}"
echo ""

# 1. Create Virtual Environment
echo -e "${GREEN}1. Creating Python Virtual Environment (.venv)...${NC}"
python3 -m venv .venv
echo "Done."

# 2. Install Dependencies
echo -e "${GREEN}2. Installing project dependencies...${NC}"
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "Done."

# 3. Create necessary directories
echo -e "${GREEN}3. Preparing output directories...${NC}"
mkdir -p output/configs
echo "Done."

echo ""
echo -e "${GREEN}SETUP SUCCESSFUL!${NC}"
echo ""
echo "To begin your first deployment, follow these steps:"
echo -e "1. Activate the environment:  ${BLUE}source .venv/bin/activate${NC}"
echo -e "2. Build the GNS3 Lab:        ${BLUE}python3 scripts/build_lab.py --intent inventory/intent.yaml --create --start --deploy --deploy-method gns3-console${NC}"
echo -e "3. Run Phase 4.a Demo:        ${BLUE}./scripts/demo_phase4a.sh${NC}"
echo ""
echo -e "${BLUE}================================================================${NC}"
