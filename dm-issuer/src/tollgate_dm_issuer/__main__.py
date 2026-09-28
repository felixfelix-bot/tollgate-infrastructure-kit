"""Production wiring + main poller entry point (spec §10, §1.3).

Loads config from ``ISSUER_CONFIG_PATH`` (default
``dm-issuer/config/config.json``), constructs all Phase I components from
environment variables, runs the async dispatcher loop, and serves the
ops FastAPI app in a background thread.

Env vars consumed:
* ``ISSUER_CONFIG_PATH`` — path to the JSON config (optional)
* ``ISSUER_NSEC`` — issuer hex private key (NEVER logged, NEVER committed)
* ``DM_ISSUER_DB_PATH`` — SQLite journal path (default
  ``/var/lib/dm-issuer/dm-issuer.db``)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Optional

import uvicorn

from .config import Config, load_config_or_default
from .dispatcher import Dispatcher, DispatcherDeps
from .grpc_payer import GrpcPayer
from .journal import SQLiteJournal
from .mint_client import MintClient
from .nostr_io import NostrIO
from .ops import Metrics, build_app
from .policy import PolicyEngine

log = logging.getLogger("tollgate_dm_issuer")


def _issuer_privkey_hex() -> Optional[str]:
    raw = os.environ.get("ISSUER_NSEC", "").strip()
    if not raw:
        return None
    if raw.startswith("nsec"):
        from pynostr.key import PrivateKey
        try:
            return PrivateKey.from_nsec(raw).hex()
        except Exception as exc:
            log.error("invalid ISSUER_NSEC nsec format: %s", exc)
            return None
    return raw


def _build_fallback_approve(url: str):
    async def _approve(quote_id: str) -> bool:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"quote_id": quote_id},
                timeout=aiohttp.ClientTimeout(total=10.0),
            ) as resp:
                return resp.status in (200, 201)
    return _approve


def _build_components() -> DispatcherDeps:
    cfg = load_config_or_default(os.environ.get("ISSUER_CONFIG_PATH"))
    db_path = os.environ.get(
        "DM_ISSUER_DB_PATH", "/var/lib/dm-issuer/dm-issuer.db")
    journal = SQLiteJournal(db_path)
    policy = PolicyEngine(config=cfg, journal=journal)
    metrics = Metrics(poll_seconds=cfg.poll_seconds)

    issuer_priv_hex = _issuer_privkey_hex()
    from pynostr.key import PublicKey
    issuer_pub_hex = PublicKey.from_npub(cfg.issuer_npub).hex()
    nostr_io = NostrIO(
        issuer_pubkey_hex=issuer_pub_hex,
        issuer_privkey_hex=issuer_priv_hex,
        relays=list(cfg.relays),
        retries=cfg.dm_retries,
        backoff_base_secs=cfg.dm_backoff_base_secs,
        lookback_default_secs=cfg.dm_lookback_default_secs,
    )
    mint_client = MintClient(base_url=cfg.mint_url)
    fallback_fn = None
    if cfg.approve_fallback_url:
        fallback_fn = _build_fallback_approve(cfg.approve_fallback_url)
    grpc_payer = GrpcPayer(
        target=cfg.grpc_target,
        retries=cfg.grpc_retries,
        backoff_base_secs=cfg.grpc_backoff_base_secs,
        fallback_approve=fallback_fn,
    )
    return DispatcherDeps(config=cfg, journal=journal, policy=policy,
                         metrics=metrics, nostr_io=nostr_io,
                         mint_client=mint_client, grpc_payer=grpc_payer)


def _run_ops_server(metrics: Metrics, *, host: str, port: int) -> None:
    app = build_app(metrics)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    deps = _build_components()

    ops_thread = threading.Thread(
        target=_run_ops_server,
        args=(deps.metrics,),
        kwargs={
            "host": deps.config.ops_host,
            "port": deps.config.ops_port,
        },
        daemon=True,
    )
    ops_thread.start()
    log.info("ops API listening on %s:%d", deps.config.ops_host,
             deps.config.ops_port)

    dispatcher = Dispatcher(deps)
    try:
        asyncio.run(dispatcher.run_forever())
    except KeyboardInterrupt:
        log.info("shutting down (KeyboardInterrupt)")
    finally:
        dispatcher.request_stop()
        if isinstance(deps.grpc_payer, GrpcPayer):
            try:
                asyncio.run(deps.grpc_payer.close())
            except Exception:
                pass
    log.info("dispatcher exited")


if __name__ == "__main__":
    main()
