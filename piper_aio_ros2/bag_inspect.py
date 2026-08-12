"""Inspect one rosbag episode without writing data."""

import argparse
import json
import sys

from .bag_config import load_stream_config
from .bag_reader import index_bag, stream_report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bag")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    streams = load_stream_config(args.config)
    bag_types, entries = index_bag(args.bag, streams)
    topics = stream_report(streams, bag_types, entries)
    errors = []
    for name, item in topics.items():
        if item["bag_type"] is None:
            errors.append(f"{name}: topic missing")
        elif item["bag_type"] != item["expected_type"]:
            errors.append(f"{name}: type mismatch")
        if item["count"] == 0:
            errors.append(f"{name}: no messages")
    report = {"ok": not errors, "bag": args.bag, "topics": topics, "errors": errors}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
