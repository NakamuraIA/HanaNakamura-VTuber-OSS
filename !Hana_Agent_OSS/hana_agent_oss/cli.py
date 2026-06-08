from __future__ import annotations

import argparse
import json
import sys

from hana_agent_oss.core.runtime import HanaAgentCore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone Hana Agent OSS deterministic CLI.")
    parser.add_argument("message", nargs="*", help="Message or deterministic command to execute.")
    parser.add_argument("--content", default="", help="Content for file.write, file.append and contextual continue commands.")
    parser.add_argument("--contains", default="", help="Expected text for file.verify_content commands.")
    parser.add_argument("--channel", default="control_center", help="Request channel.")
    return parser


def run_cli(argv: list[str] | None = None) -> dict:
    parser = build_parser()
    args = parser.parse_args(argv)
    message = " ".join(args.message).strip()
    if not message:
        message = "capabilities"

    core = HanaAgentCore()
    response = core.run(message, channel=args.channel, extra_args={"content": args.content, "contains": args.contains})
    return response.to_dict()


def main(argv: list[str] | None = None) -> int:
    payload = run_cli(argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
