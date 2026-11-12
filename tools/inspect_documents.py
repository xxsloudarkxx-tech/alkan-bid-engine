"""Read cached PDF pages or render a cited page without changing the original."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bidkit.audit import load_audit, render_page
from bidkit.config import ProjectConfig, find_project_root
from bidkit.data_store import read_json


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--document", default="")
    parser.add_argument("--page", type=int)
    parser.add_argument("--search")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    config = ProjectConfig(find_project_root(), args.project)
    for doc in load_audit(config)["documents"]:
        if args.document.lower() not in doc["name"].lower() or not doc["pages"]:
            continue
        pages = read_json(config.data_dir / "extractions" / f"{doc['sha256']}.json")["pages"]
        for page in pages:
            if args.page and page["page"] != args.page:
                continue
            if args.search and not re.search(args.search, page["text"], re.I):
                continue
            print(f"\n{doc['name']} | PDF {page['page']}\n{page['text'][:args.limit]}")
            if args.render:
                print(render_page(config, doc["name"], page["page"]))


if __name__ == "__main__":
    main()
