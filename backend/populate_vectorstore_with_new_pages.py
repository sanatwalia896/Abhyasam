"""Backward-compatible entry point for incremental Notion synchronization."""

import argparse

from populate_vectors import sync_notion_pages


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sync_notion_pages(force=args.force, dry_run=args.dry_run)
