from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .ai.factory import build_provider
from .config import Config
from .lidarr_client import LidarrClient
from .reconcile import MissingReconciler
from .resolver import StuckImportResolver
from .storage import DecisionStore

log = logging.getLogger("lidarr_ai_import")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build(config: Config) -> tuple[StuckImportResolver, MissingReconciler]:
    lidarr = LidarrClient(config.lidarr_url, config.lidarr_api_key)
    lidarr.test_connection()
    ai = build_provider(config)
    store = DecisionStore(config.db_path)
    resolver = StuckImportResolver(lidarr, ai, store, config)
    reconciler = MissingReconciler(lidarr, ai, store, config)
    return resolver, reconciler


def cmd_resolve(config: Config, _args: argparse.Namespace) -> None:
    resolver, _reconciler = _build(config)
    resolver.run_once()


def cmd_reconcile(config: Config, args: argparse.Namespace) -> None:
    _resolver, reconciler = _build(config)
    rows = reconciler.run_once()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, default=str)
        print(f"Wrote {len(rows)} row(s) to {args.json}")
        return
    for row in rows:
        print(
            f"[{row['status']:16}] {row['missing_album']} / {row['missing_title']} "
            f"(conf {row['confidence']:.2f}) -> {row['matched_existing'] or '-'} :: {row['reasoning']}"
        )
    print(f"\n{len(rows)} flagged row(s).")


def cmd_serve(config: Config, _args: argparse.Namespace) -> None:
    resolver, reconciler = _build(config)
    last_reconcile = 0.0
    log.info(
        "Starting (dry_run=%s, resolver every %ss, reconciler every %ss)",
        config.dry_run,
        config.resolver_poll_seconds,
        config.reconciler_poll_seconds,
    )
    try:
        while True:
            try:
                resolver.run_once()
                now = time.monotonic()
                if now - last_reconcile >= config.reconciler_poll_seconds:
                    reconciler.run_once()
                    last_reconcile = now
            except Exception:
                log.exception("Unhandled error in serve loop, will retry next cycle")
            time.sleep(config.resolver_poll_seconds)
    except KeyboardInterrupt:
        log.info("Stopping.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lidarr-ai-import")
    parser.add_argument("--env-file", default=".env", help="Path to .env file (default: ./.env)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("resolve", help="One-shot: resolve currently stuck manual-import items")

    p_reconcile = sub.add_parser("reconcile", help="One-shot: report missing-vs-have duplicates")
    p_reconcile.add_argument("--json", help="Write the report to this JSON file instead of stdout")

    sub.add_parser("serve", help="Run both workflows continuously")

    args = parser.parse_args(argv)
    try:
        config = Config.load(args.env_file)
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1
    _setup_logging(config.log_level)

    handlers = {"resolve": cmd_resolve, "reconcile": cmd_reconcile, "serve": cmd_serve}
    handlers[args.command](config, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
