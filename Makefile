# BGP/MPLS VPN Intent Automation - Makefile

.PHONY: help setup build render demo clean

help:
	@echo "Available commands:"
	@echo "  make setup   - Create virtual environment and install dependencies"
	@echo "  make build   - One-click GNS3 lab creation and configuration deployment"
	@echo "  make render  - Render configurations to output/configs without deploying"
	@echo "  make demo    - Run the professional Phase 4.a manageability demo"
	@echo "  make clean   - Remove generated configurations and temporary files"

setup:
	./setup.sh

build:
	@. .venv/bin/activate && python3 scripts/build_lab.py --intent inventory/intent.yaml --create --start --deploy --deploy-method gns3-console

render:
	@. .venv/bin/activate && python3 scripts/render_and_deploy.py --intent inventory/intent.yaml --write-files

demo:
	@./scripts/demo_phase4a.sh

clean:
	rm -rf output/configs/*.cfg
	find . -type d -name "__pycache__" -exec rm -rf {} +
