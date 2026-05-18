#!/usr/bin/env python3
"""Render and optionally deploy Cisco IOS configs from a service intent file."""

from __future__ import annotations

import argparse
from pathlib import Path
from automation_lib import OUTPUT_DIR, build_context, deploy_configs, load_yaml, render_configs, validate_intent, write_configs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True, type=Path, help="Path to the YAML intent file")
    parser.add_argument("--write-files", action="store_true", help="Write rendered configs to output/configs")
    parser.add_argument("--deploy", action="store_true", help="Deploy configs via Netmiko")
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
        print(f"Wrote {len(rendered)} configs to {OUTPUT_DIR}")

    if args.deploy:
        deploy_configs(context, rendered)

    if not args.write_files and not args.deploy:
        for name, config in rendered.items():
            print(f"\n===== {name} =====")
            print(config)


if __name__ == "__main__":
    main()
