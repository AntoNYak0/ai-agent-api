"""Blockchain listener — polls EVM RPCs for incoming USDC transfers and auto-credits API keys.

Runs as a background asyncio task. Checks for new Transfer events to the wallet,
matches sender address to registered API keys, and auto-top-ups credits.
"""
import asyncio
import logging
import time
import json
import os
import threading

import httpx

from app.pricing import WALLET

logger = logging.getLogger("blockchain_listener")

# RPC URLs and USDC contracts (same as facilitator.py)
RPC_URLS = {
    "eip155:8453": "https://mainnet.base.org",
    "eip155:42161": "https://arb1.arbitrum.io/rpc",
    "eip155:10": "https://mainnet.optimism.io",
}
USDC_CONTRACTS = {
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "eip155:42161": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "eip155:10": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
}
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

POLL_INTERVAL = 60  # seconds
LAST_BLOCK_FILE = "/opt/agent-api/data/last_block.json" if os.path.exists("/opt/agent-api") else "last_block.json"

_wallet_keys_lock = threading.Lock()
_wallet_keys: dict = {}  # {"0xsender": "ak-xxx"}


def register_wallet(api_key: str, wallet_address: str) -> None:
    """Link a wallet address to an API key for auto-top-up."""
    addr = wallet_address.lower()
    with _wallet_keys_lock:
        _wallet_keys[addr] = api_key
        _save_wallet_keys()
    logger.info("Wallet registered: %s -> %s...", addr, api_key[:20])


def _wallet_keys_path() -> str:
    if os.path.exists("/opt/agent-api"):
        os.makedirs("/opt/agent-api/data", exist_ok=True)
        return "/opt/agent-api/data/wallet_keys.json"
    return "wallet_keys.json"


def _load_wallet_keys() -> None:
    global _wallet_keys
    path = _wallet_keys_path()
    try:
        with open(path) as f:
            _wallet_keys = json.load(f)
        logger.info("Loaded %d wallet-key mappings", len(_wallet_keys))
    except FileNotFoundError:
        _wallet_keys = {}


def _save_wallet_keys() -> None:
    path = _wallet_keys_path()
    with open(path, "w") as f:
        json.dump(_wallet_keys, f)


async def _get_logs(rpc_url: str, contract: str, from_block: int) -> list:
    """Fetch Transfer events to our wallet since from_block."""
    topic_filter = (
        f"0x{'0' * 24}{WALLET[2:].lower()}"  # pad to 32 bytes
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getLogs",
        "params": [{
            "fromBlock": hex(from_block),
            "toBlock": "latest",
            "address": contract,
            "topics": [TRANSFER_TOPIC, None, topic_filter],
        }],
        "id": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(rpc_url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", [])
    except Exception as e:
        logger.debug("RPC %s: %s", rpc_url, e)
    return []


def _parse_transfer(log: dict) -> tuple[str, int] | None:
    """Extract (sender_address, amount_microunits) from Transfer log."""
    try:
        # topics[0]=signature, topics[1]=from, topics[2]=to
        sender = "0x" + log["topics"][1][26:]  # last 20 bytes
        amount = int(log["data"], 16)
        return sender.lower(), amount
    except (IndexError, ValueError, KeyError):
        return None


async def _poll_once() -> int:
    """Check all chains for new transfers. Returns number of new transfers processed."""
    from app.services.credits import add_credits
    from app.services.replay_guard import is_replay

    # Load last scanned block
    try:
        with open(LAST_BLOCK_FILE) as f:
            last_blocks = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        last_blocks = {}
        # First run: start from 1000 blocks ago instead of block 0
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for network, rpc_url in RPC_URLS.items():
                    resp = await client.post(rpc_url, json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1})
                    if resp.status_code == 200:
                        current = int(resp.json()["result"], 16)
                        last_blocks[network] = max(0, current - 1000)
                        logger.info("Listener starting from block %d on %s", last_blocks[network], network)
        except Exception:
            pass

    total_processed = 0

    for network, rpc_url in RPC_URLS.items():
        contract = USDC_CONTRACTS[network]
        from_block = last_blocks.get(network, 0) + 1

        logs = await _get_logs(rpc_url, contract, from_block)
        if not logs:
            continue

        max_block = max(int(log.get("blockNumber", "0x0"), 16) for log in logs)
        last_blocks[network] = max_block

        for log in logs:
            tx_hash = log.get("transactionHash", "")
            parsed = _parse_transfer(log)
            if not parsed:
                continue
            sender, amount_microunits = parsed

            # Check replay guard
            if is_replay(tx_hash, "auto_topup"):
                continue

            # Find matching API key
            with _wallet_keys_lock:
                api_key = _wallet_keys.get(sender)

            if not api_key:
                logger.debug("Unknown sender: %s — no registered API key", sender[:20])
                continue

            # Convert microunits to cents: 1 USDC = 1e6 microunits = 100 cents
            amount_cents = max(1, round(amount_microunits / 10_000))
            try:
                add_credits(api_key, amount_cents)
                logger.info("Auto-top-up: %s... +%d cents ($%.2f) for %s...",
                           sender[:10], amount_cents, amount_cents / 100, api_key[:20])
                total_processed += 1
            except Exception as e:
                logger.error("Failed to credit %s: %s", api_key[:20], e)

    # Save last blocks
    try:
        os.makedirs(os.path.dirname(LAST_BLOCK_FILE) or ".", exist_ok=True)
        with open(LAST_BLOCK_FILE, "w") as f:
            json.dump(last_blocks, f)
    except Exception:
        pass

    return total_processed


async def start_listener() -> None:
    """Start background polling loop. Call once on FastAPI startup."""
    _load_wallet_keys()
    logger.info("Blockchain listener started. Wallet: %s. Interval: %ds", WALLET, POLL_INTERVAL)
    while True:
        try:
            processed = await _poll_once()
            if processed:
                logger.info("Processed %d auto-top-ups", processed)
        except Exception as e:
            logger.error("Listener error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)
