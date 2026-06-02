"""Custom x402 facilitator — no Coinbase dependency.

Testnet: auto-approves payments (for testing).
Mainnet: verifies USDC transfers via public RPCs with failover.
EIP-3009: receiveWithAuthorization for attributable on-chain payments.
"""
import asyncio
import logging
import re
import time
import uuid

from eth_account.messages import encode_typed_data
from eth_account import Account
from eth_abi import encode as abi_encode
from web3 import Web3

from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    VerifyResponse,
    SettleResponse,
    SupportedResponse,
    SupportedKind,
)

from app.config import settings
from app.services.resilience import (
    get_circuit_breaker,
    async_retry,
    CircuitBreakerOpen as ResilienceCircuitBreakerOpen,
)
from app.errors import CircuitBreakerOpen as HttpCircuitBreakerOpen

logger = logging.getLogger("facilitator")

# Primary + backup RPC URLs per network
RPC_URLS = {
    "eip155:8453": [
        "https://mainnet.base.org",
        "https://base.llamarpc.com",
        "https://base-pokt.nodies.app",
    ],
    "eip155:42161": [
        "https://arb1.arbitrum.io/rpc",
        "https://arbitrum.llamarpc.com",
    ],
    "eip155:10": [
        "https://optimism.drpc.org",
        "https://mainnet.optimism.io",
    ],
    "eip155:84532": [
        "https://sepolia.base.org",
    ],
    "eip155:421614": [
        "https://sepolia-rollup.arbitrum.io/rpc",
    ],
    "eip155:11155420": [
        "https://sepolia.optimism.io",
    ],
    "eip155:56": [
        "https://bsc-dataseed1.binance.org",
        "https://bsc-dataseed2.binance.org",
        "https://bsc-dataseed3.binance.org",
        "https://bsc-dataseed4.binance.org",
        "https://rpc.ankr.com/bsc",
    ],
    "eip155:97": [
        "https://data-seed-prebsc-1-s1.binance.org:8545",
        "https://data-seed-prebsc-2-s1.binance.org:8545",
    ],
}

# USDC contract addresses by CAIP-2 network
USDC_CONTRACTS = {
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # Base mainnet
    "eip155:42161": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # Arbitrum mainnet
    "eip155:10": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",     # Optimism mainnet
    "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia testnet
    "eip155:421614": "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4dD",  # Arbitrum Sepolia testnet
    "eip155:11155420": "0x5fd84259d66Cd46123540766Be93DFE6D43130D7",  # Optimism Sepolia testnet
    "eip155:56": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",       # BNB Smart Chain — USDC
    "eip155:97": "0x64544969ed7EBf5f083679233325356EbE738930",       # BSC Testnet — USDC
}

# keccak256("Transfer(address,address,uint256)")
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Gas price threshold: reject if gas cost exceeds this fraction of payment
GAS_COST_THRESHOLD = 0.50       # 50% — gas must be < 50% of payment
ETH_USD_ESTIMATE = 2000.0       # rough ETH/USD rate for gas cost estimation

# ── EIP-3009: receiveWithAuthorization ──────────────────────────────

# keccak256("AuthorizationUsed(address,bytes32)")
AUTHORIZATION_USED_TOPIC = "0x3bccbb89735ecc961f3b26f5c51e96e6e60bfc9bbaa65e3e5c6c509dd35c8bce"

# keccak256("ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)")
RECEIVE_WITH_AUTH_TYPEHASH = "0xd099cc98ef71107a616c4f0f941f04c322d8e254fe26b3c6668db87aae413de8"

# receiveWithAuthorization function selector
RECEIVE_WITH_AUTH_SELECTOR = "0xef55bec6"

# EIP-712 domain by CAIP-2 network (USDC FiatTokenV2 contracts)
EIP3009_DOMAINS = {
    "eip155:8453": {
        "name": "USD Coin",
        "version": "2",
        "chainId": 8453,
        "verifyingContract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "eip155:84532": {
        "name": "USD Coin",
        "version": "2",
        "chainId": 84532,
        "verifyingContract": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    },
}

# Minimal ABI for EIP-3009 USDC functions + AuthorizationUsed event
USDC_EIP3009_ABI = [
    {
        "inputs": [
            {"name": "authorizer", "type": "address"},
            {"name": "nonce", "type": "bytes32"},
        ],
        "name": "authorizationState",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "authorizer", "type": "address"},
            {"indexed": True, "name": "nonce", "type": "bytes32"},
        ],
        "name": "AuthorizationUsed",
        "type": "event",
    },
]

# Min payment for EIP-3009 (server pays gas) — below this, client uses Transfer path
EIP3009_MIN_PAYMENT_MICROUNITS = 10_000  # $0.01 minimum, gas on L2 is ~$0.001

# ── Tx hash format validation ──────────────────────────────────────

def _is_valid_evm_tx_hash(tx_hash: str) -> bool:
    """Validate EVM transaction hash: 0x + 64 lowercase/uppercase hex chars."""
    return bool(re.match(r'^0x[a-fA-F0-9]{64}$', tx_hash))

def _is_valid_tron_tx_hash(tx_hash: str) -> bool:
    """Validate TRON transaction hash: 64 hex chars, optional 0x prefix."""
    return bool(re.match(r'^(0x)?[a-fA-F0-9]{64}$', tx_hash))


class DirectFacilitator:
    """Self-hosted facilitator that verifies USDC payments directly."""

    def __init__(self, testnet: bool = True, pay_to: str = ""):
        self.testnet = testnet
        self.pay_to = pay_to.lower() if pay_to else ""

    def get_supported(self) -> SupportedResponse:
        networks = (
            ["eip155:84532", "eip155:421614", "eip155:11155420", "eip155:97"]
            if self.testnet
            else ["eip155:8453", "eip155:42161", "eip155:10", "eip155:56"]
        )
        return SupportedResponse(
            kinds=[
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network=net,
                )
                for net in networks
            ],
            extensions=[],
            signers={},
        )

    async def verify(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        if self.testnet:
            auth = payload.payload.get("authorization")
            tag = "eip3009" if auth else (payload.payload.get("transactionHash", "no-tx")[:16])
            logger.info(
                "Testnet auto-approve: tag=%s payer=%s",
                tag, payload.payload.get("payer", "testnet"),
            )
            return VerifyResponse(
                is_valid=True,
                payer=payload.payload.get("payer", "testnet"),
            )

        # EIP-3009 path: authorization signed message → off-chain verification
        if payload.payload.get("authorization"):
            return await self._verify_eip3009(payload, requirements)

        # Existing Transfer path: transactionHash → on-chain receipt check
        return await self._verify_onchain_evm(payload, requirements)

    async def _verify_onchain_evm(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """Verify a real USDC payment via public RPC with failover + amount/contract checks."""
        import httpx

        network = requirements.network
        rpc_urls = RPC_URLS.get(network, ["https://mainnet.base.org"])
        tx_hash = payload.payload.get("transactionHash", "")
        corr_id = str(uuid.uuid4())[:8]

        if not tx_hash:
            logger.warning("cid=%s reason=missing_tx_hash", corr_id)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="missing_tx_hash",
                invalid_message="Payment payload must include transactionHash",
            )

        # Validate tx hash format: must be 0x + 64 hex chars for EVM
        if not _is_valid_evm_tx_hash(tx_hash):
            logger.warning("cid=%s reason=invalid_tx_hash_format tx=%s", corr_id, tx_hash[:20])
            return VerifyResponse(
                is_valid=False,
                invalid_reason="invalid_tx_hash_format",
                invalid_message="Invalid transaction hash format. Expected 0x + 64 hex characters.",
            )

        expected_contract = USDC_CONTRACTS.get(network)
        if not expected_contract:
            logger.warning("cid=%s reason=unsupported_network network=%s", corr_id, network)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="unsupported_network",
                invalid_message=f"Network {network} not supported. Use Base (eip155:8453), Arbitrum (eip155:42161), Optimism (eip155:10), or BNB Chain (eip155:56)",
            )

        logger.info("cid=%s verifying tx=%s network=%s", corr_id, tx_hash[:16], network)

        receipt = None
        last_error = None
        tried_urls = []

        # ── Circuit breaker per chain ──
        cb = get_circuit_breaker(f"evm-rpc-{network}")
        try:
            cb.before_call()
        except ResilienceCircuitBreakerOpen as e:
            raise HttpCircuitBreakerOpen(
                message=f"RPC circuit breaker open for {network}: {e}",
                service_name=e.name,
                retry_after_seconds=int(e.retry_after_seconds),
            )

        async def _rpc_call(rpc_url: str) -> dict | None:
            """Single RPC eth_getTransactionReceipt call — wrapped by async_retry."""
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_getTransactionReceipt",
                        "params": [tx_hash],
                    },
                )
                if resp.status_code == 413:
                    raise RuntimeError(f"RPC {rpc_url[:40]}: 413 Payload Too Large")
                if resp.status_code != 200:
                    raise RuntimeError(f"RPC {rpc_url[:40]}: HTTP {resp.status_code}")
                data = resp.json()
                result = data.get("result")
                if not result:
                    return None  # tx not found yet (not an error)
                return result

        for rpc_url in rpc_urls:
            tried_urls.append(rpc_url)
            try:
                receipt = await async_retry(
                    _rpc_call,
                    rpc_url,
                    max_retries=settings.rpc_retry_max_attempts,
                    base_delay=0.5,
                    max_delay=5.0,
                    jitter=settings.retry_jitter_enabled,
                    max_cumulative_timeout=15.0,
                    retryable_exceptions=(RuntimeError,),
                )
                if receipt:
                    cb.on_success()
                    break
                else:
                    # tx not found — not a failure, just not confirmed yet
                    last_error = f"RPC {rpc_url[:40]}: tx not found"
            except Exception as e:
                last_error = f"RPC {rpc_url[:40]}: {e}"
                logger.debug("cid=%s rpc=%s error=%s", corr_id, rpc_url[:40], e)
                continue

        # If all URLs failed, trip the circuit breaker
        if not receipt:
            cb.on_failure()

        if not receipt:
            logger.warning("cid=%s tx=%s reason=tx_not_found tried=%s", corr_id, tx_hash[:16], tried_urls)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="tx_not_found",
                invalid_message=f"Transaction {tx_hash[:10]}... not found on chain. Tried {len(tried_urls)} RPC(s). Wait for confirmation.",
            )

        if receipt.get("status") != "0x1":
            logger.warning("cid=%s tx=%s reason=tx_reverted status=%s", corr_id, tx_hash[:16], receipt.get("status"))
            return VerifyResponse(
                is_valid=False,
                invalid_reason="tx_failed",
                invalid_message="Transaction reverted or failed",
            )

        # 1.5. Gas cost threshold — reject if gas > 50% of payment
        required_amount_str = requirements.amount
        if required_amount_str:
            try:
                required_amount = int(required_amount_str)
                gas_used_hex = receipt.get("gasUsed", "0x0")
                gas_price_hex = receipt.get("effectiveGasPrice", "0x0")
                gas_used = int(gas_used_hex, 16) if isinstance(gas_used_hex, str) else gas_used_hex
                gas_price = int(gas_price_hex, 16) if isinstance(gas_price_hex, str) else gas_price_hex
                gas_cost_wei = gas_used * gas_price
                gas_cost_usd = (gas_cost_wei / 1e18) * ETH_USD_ESTIMATE
                gas_cost_microunits = int(gas_cost_usd * 1e6)

                if required_amount > 0 and gas_cost_microunits > required_amount * GAS_COST_THRESHOLD:
                    logger.warning(
                        "cid=%s tx=%s reason=gas_too_high gas=%.4f USD payment=%.4f USD ratio=%.1f%%",
                        corr_id, tx_hash[:16],
                        gas_cost_usd,
                        required_amount / 1e6,
                        (gas_cost_microunits / required_amount) * 100 if required_amount > 0 else 0,
                    )
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="gas_cost_too_high",
                        invalid_message=(
                            f"Gas cost (≈${gas_cost_usd:.2f}) exceeds {GAS_COST_THRESHOLD*100:.0f}% "
                            f"of payment (${required_amount / 1e6:.4f}). "
                            f"Try using a network with lower gas fees."
                        ),
                    )
            except (ValueError, TypeError, ZeroDivisionError):
                pass  # If we can't parse gas info, proceed anyway

        # 2. Find the USDC Transfer event in logs (match contract + topic)
        expected_contract_lower = expected_contract.lower()
        transfer_amount = None
        transfer_recipient = None

        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            log_address = log.get("address", "").lower()

            if topics and topics[0] == TRANSFER_EVENT_TOPIC:
                if log_address != expected_contract_lower:
                    continue

                if len(topics) >= 3:
                    transfer_recipient = "0x" + topics[2][-40:]

                log_data = log.get("data", "0x")
                if log_data and log_data != "0x":
                    transfer_amount = int(log_data, 16)

                break  # Found our USDC Transfer

        if transfer_recipient is None:
            logger.warning("cid=%s tx=%s reason=no_usdc_transfer contract=%s logs=%d",
                corr_id, tx_hash[:16], expected_contract, len(receipt.get("logs", [])))
            return VerifyResponse(
                is_valid=False,
                invalid_reason="no_usdc_transfer",
                invalid_message=f"No USDC Transfer event from contract {expected_contract} found in transaction logs",
            )

        # 3. Check recipient
        transfer_recipient_lower = transfer_recipient.lower()
        if self.pay_to and transfer_recipient_lower != self.pay_to:
            logger.warning("cid=%s tx=%s reason=wrong_recipient got=%s expected=%s",
                corr_id, tx_hash[:16], transfer_recipient, self.pay_to)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="wrong_recipient",
                invalid_message=f"USDC sent to {transfer_recipient}, expected {self.pay_to}",
            )

        # 4. Check amount
        required_amount_str = requirements.amount
        if required_amount_str and transfer_amount is not None:
            try:
                required_amount = int(required_amount_str)
            except (ValueError, TypeError):
                required_amount = 0

            if required_amount > 0 and transfer_amount < required_amount:
                logger.warning("cid=%s tx=%s reason=insufficient_amount got=%.4f need=%.4f",
                    corr_id, tx_hash[:16],
                    transfer_amount / 1e6,
                    required_amount / 1e6)
                return VerifyResponse(
                    is_valid=False,
                    invalid_reason="insufficient_amount",
                    invalid_message=(
                        f"Payment insufficient: got {transfer_amount / 1e6:.4f} USDC, "
                        f"required at least {required_amount / 1e6:.4f} USDC"
                    ),
                )

        logger.info("cid=%s tx=%s result=verified payer=%s amount=%.4f USDC",
            corr_id, tx_hash[:16],
            receipt.get("from", "")[:10],
            transfer_amount / 1e6 if transfer_amount else 0)
        return VerifyResponse(
            is_valid=True,
            payer=receipt.get("from", ""),
        )

    async def settle(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> SettleResponse:
        if self.testnet:
            tx_id = payload.payload.get("authorization", {}).get("nonce",
                    payload.payload.get("transactionHash", "testnet-tx"))
            if isinstance(tx_id, str) and tx_id.startswith("0x"):
                tx_id = tx_id[:20] + "..."
            return SettleResponse(
                success=True,
                payer=payload.payload.get("payer", "testnet"),
                transaction=str(tx_id),
                network=requirements.network,
                amount=requirements.amount,
            )

        # EIP-3009 path: submit receiveWithAuthorization on-chain
        if payload.payload.get("authorization"):
            return await self._settle_eip3009(payload, requirements)

        # Existing Transfer path: no-op (client already paid gas)
        return SettleResponse(
            success=True,
            payer=payload.payload.get("payer", ""),
            transaction=payload.payload.get("transactionHash", ""),
            network=requirements.network,
            amount=requirements.amount,
        )

    # ── EIP-3009 methods ──────────────────────────────────────────

    async def _verify_eip3009(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """Off-chain EIP-712 signature verification for receiveWithAuthorization.

        Steps:
        1. Extract and validate authorization fields
        2. Reconstruct EIP-712 typed data
        3. ecrecover → compare with `from`
        4. Check time window (validAfter <= now < validBefore)
        5. Check recipient matches pay_to
        6. eth_call authorizationState(from, nonce) — must be unused
        7. Check minimum payment amount for server-paid gas
        """
        import httpx

        auth = payload.payload.get("authorization", {})
        if not isinstance(auth, dict):
            logger.warning("eip3009 reason=invalid_auth_type type=%s", type(auth).__name__)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="invalid_authorization",
                invalid_message="authorization must be an object with EIP-3009 fields",
            )

        corr_id = str(uuid.uuid4())[:8]
        network = requirements.network

        # 1. Extract fields
        from_addr_raw = auth.get("from", "")
        value_raw = auth.get("value", "0")
        valid_after_raw = auth.get("validAfter", 0)
        valid_before_raw = auth.get("validBefore", 0)
        nonce_raw = auth.get("nonce", "")
        v_raw = auth.get("v", 0)
        r_raw = auth.get("r", "")
        s_raw = auth.get("s", "")

        # Validate required fields present
        missing = []
        if not from_addr_raw: missing.append("from")
        if not nonce_raw: missing.append("nonce")
        if not r_raw: missing.append("r")
        if not s_raw: missing.append("s")
        if v_raw is None or (isinstance(v_raw, str) and not v_raw): missing.append("v")
        if missing:
            logger.warning("eip3009 cid=%s reason=missing_fields fields=%s", corr_id, missing)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="missing_authorization_fields",
                invalid_message=f"Missing required EIP-3009 fields: {', '.join(missing)}",
            )

        # Parse/coerce types
        try:
            from_addr = Web3.to_checksum_address(from_addr_raw)
            value = int(value_raw)
            valid_after = int(valid_after_raw)
            valid_before = int(valid_before_raw)
            v = int(v_raw)
        except (ValueError, TypeError) as e:
            logger.warning("eip3009 cid=%s reason=parse_error error=%s", corr_id, e)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="invalid_field_type",
                invalid_message=f"Failed to parse EIP-3009 field: {e}",
            )

        # Normalize v for Ethereum (27 or 28)
        if v in (0, 1):
            v += 27

        # Normalize nonce to bytes32 hex
        if isinstance(nonce_raw, int):
            nonce_bytes32 = Web3.to_bytes(nonce_raw).rjust(32, b'\x00')
        elif nonce_raw.startswith("0x"):
            nonce_hex = nonce_raw[2:].zfill(64)
            nonce_bytes32 = bytes.fromhex(nonce_hex)
        else:
            nonce_bytes32 = bytes.fromhex(nonce_raw.zfill(64))

        # Normalize r/s to bytes32
        if isinstance(r_raw, str):
            r_bytes = bytes.fromhex(r_raw.replace("0x", "").zfill(64))
        else:
            r_bytes = bytes(r_raw).rjust(32, b'\x00')
        if isinstance(s_raw, str):
            s_bytes = bytes.fromhex(s_raw.replace("0x", "").zfill(64))
        else:
            s_bytes = bytes(s_raw).rjust(32, b'\x00')

        # 2. Get EIP-712 domain for this network
        domain = EIP3009_DOMAINS.get(network)
        if not domain:
            logger.warning("eip3009 cid=%s reason=unsupported_network network=%s", corr_id, network)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="unsupported_network",
                invalid_message=f"EIP-3009 not supported on {network}. Use Base (eip155:8453).",
            )

        # 3. Check recipient matches pay_to
        pay_to_checksummed = Web3.to_checksum_address(self.pay_to) if self.pay_to else ""
        auth_to_raw = auth.get("to", "")
        if auth_to_raw:
            try:
                auth_to = Web3.to_checksum_address(auth_to_raw)
            except ValueError:
                auth_to = ""
            if auth_to and pay_to_checksummed and auth_to.lower() != pay_to_checksummed.lower():
                logger.warning("eip3009 cid=%s reason=wrong_recipient got=%s expected=%s",
                    corr_id, auth_to, pay_to_checksummed)
                return VerifyResponse(
                    is_valid=False,
                    invalid_reason="wrong_recipient",
                    invalid_message=f"Authorization 'to' ({auth_to}) does not match payTo ({pay_to_checksummed})",
                )

        # 4. Check time window
        now = int(time.time())
        if now < valid_after:
            logger.warning("eip3009 cid=%s reason=not_yet_valid now=%d validAfter=%d",
                corr_id, now, valid_after)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="auth_not_yet_valid",
                invalid_message=f"Authorization not valid until {valid_after} (now: {now})",
            )
        if now >= valid_before:
            logger.warning("eip3009 cid=%s reason=expired now=%d validBefore=%d",
                corr_id, now, valid_before)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="auth_expired",
                invalid_message=f"Authorization expired at {valid_before} (now: {now})",
            )

        # 5. Check minimum payment (server pays gas — don't settle tiny amounts)
        if value < EIP3009_MIN_PAYMENT_MICROUNITS:
            logger.warning("eip3009 cid=%s reason=below_min value=%d min=%d",
                corr_id, value, EIP3009_MIN_PAYMENT_MICROUNITS)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="amount_too_small",
                invalid_message=(
                    f"Payment ({value / 1e6:.4f} USDC) below minimum "
                    f"({EIP3009_MIN_PAYMENT_MICROUNITS / 1e6:.4f} USDC) for EIP-3009. "
                    f"Use standard Transfer for smaller amounts."
                ),
            )

        # 6. Reconstruct EIP-712 typed data and recover signer
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "ReceiveWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "ReceiveWithAuthorization",
            "domain": domain,
            "message": {
                "from": from_addr,
                "to": pay_to_checksummed,
                "value": value,
                "validAfter": valid_after,
                "validBefore": valid_before,
                "nonce": "0x" + nonce_bytes32.hex(),
            },
        }

        try:
            encoded = encode_typed_data(full_message=typed_data)
            recovered = Account._recover_hash(encoded.body, vrs=(v, r_bytes, s_bytes))
        except Exception as e:
            logger.warning("eip3009 cid=%s reason=ecrecover_failed error=%s", corr_id, e)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="invalid_signature",
                invalid_message=f"EIP-712 signature verification failed: {e}",
            )

        if recovered.lower() != from_addr.lower():
            logger.warning("eip3009 cid=%s reason=signer_mismatch recovered=%s from=%s",
                corr_id, recovered, from_addr)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="invalid_signature",
                invalid_message=f"Recovered {recovered}, expected {from_addr}",
            )

        # 7. Check authorizationState on-chain (nonce must NOT be used)
        usdc_contract = USDC_CONTRACTS.get(network)
        if not usdc_contract:
            logger.warning("eip3009 cid=%s reason=no_contract network=%s", corr_id, network)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="unsupported_network",
                invalid_message=f"No USDC contract for {network}",
            )

        # Encode authorizationState call
        auth_state_selector = Web3.keccak(
            text="authorizationState(address,bytes32)"
        )[:4]
        call_data = (
            "0x"
            + auth_state_selector.hex()
            + abi_encode(["address", "bytes32"], [from_addr, nonce_bytes32]).hex()
        )

        rpc_urls = RPC_URLS.get(network, ["https://mainnet.base.org"])
        nonce_used = True  # fail-closed: assume used
        last_error = None

        cb = get_circuit_breaker(f"evm-rpc-{network}")
        try:
            cb.before_call()
        except ResilienceCircuitBreakerOpen as e:
            raise HttpCircuitBreakerOpen(
                message=f"RPC circuit breaker open for {network}: {e}",
                service_name=e.name,
                retry_after_seconds=int(e.retry_after_seconds),
            )

        async def _call_auth_state(rpc_url: str) -> bool:
            """eth_call authorizationState — returns True if nonce IS used."""
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_call",
                        "params": [
                            {"to": usdc_contract, "data": call_data},
                            "latest",
                        ],
                    },
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"RPC {rpc_url[:40]}: HTTP {resp.status_code}")
                result = resp.json().get("result", "0x")
                # Decode: 32-byte hex → int → bool
                return int(result, 16) != 0

        for rpc_url in rpc_urls:
            try:
                nonce_used = await async_retry(
                    _call_auth_state,
                    rpc_url,
                    max_retries=settings.rpc_retry_max_attempts,
                    base_delay=0.5,
                    max_delay=5.0,
                    jitter=settings.retry_jitter_enabled,
                    max_cumulative_timeout=15.0,
                    retryable_exceptions=(RuntimeError,),
                )
                cb.on_success()
                last_error = None
                break
            except Exception as e:
                last_error = str(e)
                logger.debug("eip3009 cid=%s rpc=%s error=%s", corr_id, rpc_url[:40], e)
                continue

        if last_error:
            cb.on_failure()
            logger.warning("eip3009 cid=%s reason=rpc_error auth_state_failed=%s",
                corr_id, last_error)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="rpc_error",
                invalid_message=f"Failed to check authorization state: {last_error}",
            )

        if nonce_used:
            logger.warning("eip3009 cid=%s reason=nonce_used authorizer=%s nonce=%s",
                corr_id, from_addr, "0x" + nonce_bytes32.hex())
            return VerifyResponse(
                is_valid=False,
                invalid_reason="nonce_already_used",
                invalid_message="This authorization nonce has already been used on-chain",
            )

        logger.info("eip3009 cid=%s result=verified authorizer=%s value=%.4f USDC network=%s",
            corr_id, from_addr, value / 1e6, network)
        return VerifyResponse(
            is_valid=True,
            payer=from_addr,
        )

    async def _settle_eip3009(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> SettleResponse:
        """Submit receiveWithAuthorization transaction on-chain.

        Server pays gas. Must have facilitator_eip3009_private_key configured.
        Emits AuthorizationUsed(authorizer, nonce) — attributable event.
        """
        import httpx

        auth = payload.payload.get("authorization", {})
        network = requirements.network
        corr_id = str(uuid.uuid4())[:8]

        # 1. Check private key configured
        pk = settings.facilitator_eip3009_private_key.strip()
        if not pk:
            logger.error("eip3009 cid=%s reason=no_private_key", corr_id)
            return SettleResponse(
                success=False,
                payer=auth.get("from", ""),
                transaction="",
                error_reason="eip3009_not_configured",
                error_message="EIP-3009 settlement requires facilitator_eip3009_private_key",
                network=network,
                amount=requirements.amount,
            )

        # 2. Build server account from private key
        try:
            server_account = Account.from_key(pk)
        except Exception as e:
            logger.error("eip3009 cid=%s reason=invalid_private_key error=%s", corr_id, e)
            return SettleResponse(
                success=False,
                payer=auth.get("from", ""),
                error_reason="invalid_private_key",
                error_message=f"Invalid EIP-3009 private key: {e}",
                network=network,
                amount=requirements.amount,
            )

        # 3. Get network params
        domain = EIP3009_DOMAINS.get(network)
        if not domain:
            return SettleResponse(
                success=False,
                payer=auth.get("from", ""),
                error_reason="unsupported_network",
                error_message=f"EIP-3009 settlement not supported on {network}",
                network=network,
                amount=requirements.amount,
            )

        usdc_contract = USDC_CONTRACTS.get(network)
        if not usdc_contract:
            return SettleResponse(
                success=False,
                payer=auth.get("from", ""),
                error_reason="no_contract",
                error_message=f"No USDC contract for {network}",
                network=network,
                amount=requirements.amount,
            )

        # 4. Parse authorization fields
        try:
            from_addr = Web3.to_checksum_address(auth.get("from", ""))
            to_addr = Web3.to_checksum_address(self.pay_to)
            value = int(auth["value"])
            valid_after = int(auth["validAfter"])
            valid_before = int(auth["validBefore"])
            v = int(auth["v"])
            if v in (0, 1):
                v += 27
        except (KeyError, ValueError, TypeError) as e:
            return SettleResponse(
                success=False,
                payer=auth.get("from", ""),
                error_reason="invalid_fields",
                error_message=f"Failed to parse EIP-3009 fields: {e}",
                network=network,
                amount=requirements.amount,
            )

        # Normalize nonce/r/s to bytes32
        nonce_raw = auth["nonce"]
        if isinstance(nonce_raw, int):
            nonce_bytes32 = Web3.to_bytes(nonce_raw).rjust(32, b'\x00')
        elif nonce_raw.startswith("0x"):
            nonce_bytes32 = bytes.fromhex(nonce_raw[2:].zfill(64))
        else:
            nonce_bytes32 = bytes.fromhex(nonce_raw.zfill(64))

        r_bytes = bytes.fromhex(auth["r"].replace("0x", "").zfill(64))
        s_bytes = bytes.fromhex(auth["s"].replace("0x", "").zfill(64))

        # 5. Encode receiveWithAuthorization call
        fn_selector = bytes.fromhex(RECEIVE_WITH_AUTH_SELECTOR[2:])  # remove 0x
        encoded_params = abi_encode(
            ["address", "address", "uint256", "uint256", "uint256", "bytes32", "uint8", "bytes32", "bytes32"],
            [from_addr, to_addr, value, valid_after, valid_before, nonce_bytes32, v, r_bytes, s_bytes],
        )
        call_data = "0x" + (fn_selector + encoded_params).hex()

        rpc_urls = RPC_URLS.get(network, ["https://mainnet.base.org"])
        chain_id = domain["chainId"]

        # 6. Get nonce + gas price via RPC
        async with httpx.AsyncClient(timeout=20) as client:

            async def _rpc(method: str, params: list):
                resp = await client.post(
                    rpc_urls[0],
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"RPC {method}: HTTP {resp.status_code}")
                return resp.json()

            try:
                # Get server nonce
                nonce_resp = await _rpc("eth_getTransactionCount", [
                    server_account.address, "pending"
                ])
                nonce = int(nonce_resp["result"], 16)

                # Get gas price
                gas_price_resp = await _rpc("eth_gasPrice", [])
                gas_price = int(gas_price_resp["result"], 16)

                # Apply user max fee or auto (1.2x gas price)
                max_fee = settings.eip3009_max_gas_fee_wei
                if max_fee <= 0:
                    max_fee = int(gas_price * 1.2)

                # Estimate gas or use hardcoded 55K with 1.3x buffer
                try:
                    estimate_resp = await _rpc("eth_estimateGas", [{
                        "from": server_account.address,
                        "to": usdc_contract,
                        "data": call_data,
                    }])
                    gas_limit = int(int(estimate_resp["result"], 16) * 1.3)
                except Exception:
                    gas_limit = 55_000  # receiveWithAuthorization typical gas

                # 7. Build and sign transaction (EIP-1559)
                tx = {
                    "type": 2,
                    "chainId": chain_id,
                    "from": server_account.address,
                    "to": usdc_contract,
                    "value": 0,
                    "gas": gas_limit,
                    "maxFeePerGas": max_fee,
                    "maxPriorityFeePerGas": min(int(gas_price * 0.1), int(max_fee * 0.5)),
                    "nonce": nonce,
                    "data": call_data,
                }
                signed = Account.sign_transaction(tx, pk)
                raw_tx = signed.raw_transaction.hex()

                logger.info("eip3009 cid=%s sending tx gas=%d maxFee=%d nonce=%d",
                    corr_id, gas_limit, max_fee, nonce)

                # 8. Send raw transaction
                send_resp = await _rpc("eth_sendRawTransaction", ["0x" + raw_tx])
                if "error" in send_resp:
                    error_msg = send_resp["error"].get("message", str(send_resp["error"]))
                    logger.error("eip3009 cid=%s reason=send_failed error=%s", corr_id, error_msg)
                    return SettleResponse(
                        success=False,
                        payer=from_addr,
                        error_reason="tx_send_failed",
                        error_message=f"Transaction failed: {error_msg}",
                        network=network,
                        amount=requirements.amount,
                    )

                tx_hash = send_resp["result"]
                logger.info("eip3009 cid=%s tx_sent=%s", corr_id, tx_hash)

                # 9. Wait for receipt (poll up to 120s)
                for _ in range(40):  # 40 * 3s = 120s
                    await asyncio.sleep(3)
                    rcpt_resp = await _rpc("eth_getTransactionReceipt", [tx_hash])
                    receipt = rcpt_resp.get("result")
                    if not receipt:
                        continue

                    if receipt.get("status") != "0x1":
                        logger.error("eip3009 cid=%s reason=tx_reverted tx=%s", corr_id, tx_hash)
                        return SettleResponse(
                            success=False,
                            payer=from_addr,
                            transaction=tx_hash,
                            error_reason="tx_reverted",
                            error_message="Transaction reverted on-chain",
                            network=network,
                            amount=requirements.amount,
                        )

                    # Verify AuthorizationUsed event in logs
                    event_found = False
                    for log in receipt.get("logs", []):
                        topics = log.get("topics", [])
                        if (log.get("address", "").lower() == usdc_contract.lower()
                                and topics and topics[0] == AUTHORIZATION_USED_TOPIC):
                            event_found = True
                            break

                    if not event_found:
                        logger.error("eip3009 cid=%s reason=no_event tx=%s", corr_id, tx_hash)
                        return SettleResponse(
                            success=False,
                            payer=from_addr,
                            transaction=tx_hash,
                            error_reason="authorization_event_missing",
                            error_message="AuthorizationUsed event not found in receipt logs",
                            network=network,
                            amount=requirements.amount,
                        )

                    logger.info("eip3009 cid=%s settled tx=%s authorizer=%s",
                        corr_id, tx_hash, from_addr)
                    return SettleResponse(
                        success=True,
                        payer=from_addr,
                        transaction=tx_hash,
                        network=network,
                        amount=requirements.amount,
                    )

                # Timeout
                logger.error("eip3009 cid=%s reason=timeout tx=%s", corr_id, tx_hash)
                return SettleResponse(
                    success=False,
                    payer=from_addr,
                    transaction=tx_hash,
                    error_reason="tx_timeout",
                    error_message="Transaction not confirmed within 120s",
                    network=network,
                    amount=requirements.amount,
                )

            except Exception as e:
                logger.error("eip3009 cid=%s reason=exception error=%s", corr_id, e)
                return SettleResponse(
                    success=False,
                    payer=auth.get("from", ""),
                    transaction="",
                    error_reason="settlement_error",
                    error_message=f"EIP-3009 settlement failed: {e}",
                    network=network,
                    amount=requirements.amount,
                )


# ── TRON / TRC-20 ─────────────────────────────────────────────────

TRON_NETWORK = "tron:0x2b6653dc"  # TRON mainnet CAIP-2
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRONGRID_API = "https://api.trongrid.io"

# TRC-20 Transfer event signature: keccak256("Transfer(address,address,uint256)")
# On TRON, event topics are hex-encoded the same way as Ethereum
TRC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class TronFacilitator:
    """Facilitator that verifies USDT TRC-20 payments on TRON via TronGrid API."""

    def __init__(self, pay_to_tron: str):
        self.pay_to = pay_to_tron

    def get_supported(self) -> SupportedResponse:
        return SupportedResponse(
            kinds=[
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network=TRON_NETWORK,
                )
            ],
            extensions=[],
            signers={},
        )

    async def verify(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        return await self._verify_trc20(payload, requirements)

    async def _verify_trc20(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """Verify a USDT TRC-20 payment via TronGrid API."""
        import httpx

        tx_hash = payload.payload.get("transactionHash", "")

        if not tx_hash:
            logger.warning("TRON verification rejected: missing transactionHash")
            return VerifyResponse(
                is_valid=False,
                invalid_reason="missing_tx_hash",
                invalid_message="Payment payload must include transactionHash",
            )

        # Validate tx hash format: TRON uses 64 hex chars (with optional 0x prefix)
        if not _is_valid_tron_tx_hash(tx_hash):
            logger.warning("TRON verification rejected: invalid tx hash format %s...", tx_hash[:20])
            return VerifyResponse(
                is_valid=False,
                invalid_reason="invalid_tx_hash_format",
                invalid_message="Invalid transaction hash format. Expected 64 hex characters.",
            )

        logger.info("Verifying TRC-20 tx %s... on TRON", tx_hash[:16])

        # ── Circuit breaker for TRON RPC ──
        cb = get_circuit_breaker("tron-rpc")
        try:
            cb.before_call()
        except ResilienceCircuitBreakerOpen as e:
            raise HttpCircuitBreakerOpen(
                message=f"TRON RPC circuit breaker open: {e}",
                service_name=e.name,
                retry_after_seconds=int(e.retry_after_seconds),
            )

        async def _fetch_events() -> list:
            """Fetch TRON transaction events — wrapped by async_retry."""
            async with httpx.AsyncClient(timeout=20) as client:
                url = f"{TRONGRID_API}/v1/transactions/{tx_hash}/events"
                resp = await client.get(url)
                if resp.status_code != 200:
                    raise RuntimeError(f"TronGrid HTTP {resp.status_code}")
                return resp.json().get("data", [])

        try:
            events = await async_retry(
                _fetch_events,
                max_retries=3,
                base_delay=1.0,
                max_delay=10.0,
                jitter=settings.retry_jitter_enabled,
                max_cumulative_timeout=30.0,
                retryable_exceptions=(RuntimeError,),
            )
            cb.on_success()

            if not events:
                logger.warning("Tx %s... no events found on TRON", tx_hash[:16])
                return VerifyResponse(
                    is_valid=False,
                    invalid_reason="tx_not_found",
                    invalid_message=f"Transaction {tx_hash[:10]}... not found on TRON.",
                )

            # Process events (same logic as before, just moved inside the try block)
            transfer_amount = None
            transfer_recipient = None

            for event in events:
                contract = event.get("contract_address", event.get("contract", ""))
                if contract != USDT_TRC20_CONTRACT:
                    continue

                result = event.get("result", {})
                to_addr = result.get("to", result.get("_to", ""))
                value_str = result.get("value", result.get("_value", "0"))

                if to_addr:
                    transfer_recipient = to_addr
                if value_str:
                    transfer_amount = int(str(value_str))

                raw_topics = event.get("raw_data", {}).get("topics", event.get("topics", []))
                if raw_topics and raw_topics[0] == TRC20_TRANSFER_TOPIC:
                    if len(raw_topics) >= 3:
                        transfer_recipient = TronFacilitator._hex_to_tron_address(raw_topics[2])
                    raw_data_hex = event.get("raw_data", {}).get("data", event.get("data", "0x"))
                    if raw_data_hex and raw_data_hex != "0x":
                        transfer_amount = int(raw_data_hex, 16)

                if transfer_recipient:
                    break

            if transfer_recipient is None:
                logger.warning(
                    "Tx %s... no USDT TRC-20 Transfer from %s",
                    tx_hash[:16], USDT_TRC20_CONTRACT,
                )
                return VerifyResponse(
                    is_valid=False,
                    invalid_reason="no_trc20_transfer",
                    invalid_message=f"No USDT TRC-20 Transfer event from {USDT_TRC20_CONTRACT} found",
                )

            # 3. Check recipient
            if self.pay_to and transfer_recipient != self.pay_to:
                logger.warning(
                    "Tx %s... wrong TRON recipient: got %s, expected %s",
                    tx_hash[:16], transfer_recipient, self.pay_to,
                )
                return VerifyResponse(
                    is_valid=False,
                    invalid_reason="wrong_recipient",
                    invalid_message=f"USDT sent to {transfer_recipient}, expected {self.pay_to}",
                )

            # 4. Check amount (USDT has 6 decimals on TRON)
            required_amount_str = requirements.amount
            if required_amount_str and transfer_amount is not None:
                try:
                    required_amount = int(required_amount_str)
                except (ValueError, TypeError):
                    required_amount = 0

                if required_amount > 0 and transfer_amount < required_amount:
                    logger.warning(
                        "Tx %s... insufficient TRC-20 amount: got %.4f USDT, need %.4f USDT",
                        tx_hash[:16],
                        transfer_amount / 1e6,
                        required_amount / 1e6,
                    )
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="insufficient_amount",
                        invalid_message=(
                            f"Payment insufficient: got {transfer_amount / 1e6:.4f} USDT, "
                            f"required at least {required_amount / 1e6:.4f} USDT"
                        ),
                    )

            logger.info(
                "TRC-20 Payment verified: tx=%s... recipient=%s amount=%.4f USDT",
                tx_hash[:16],
                transfer_recipient[:10],
                transfer_amount / 1e6 if transfer_amount else 0,
            )
            return VerifyResponse(
                is_valid=True,
                payer=transfer_recipient[:10],
            )

        except Exception as e:
            cb.on_failure()
            logger.error("TRON verification failed for tx %s...: %s", tx_hash[:16], e)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="tron_rpc_error",
                invalid_message=f"TRON payment verification failed: {e}",
            )

    async def settle(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> SettleResponse:
        return SettleResponse(
            success=True,
            payer=payload.payload.get("payer", ""),
            transaction=payload.payload.get("transactionHash", ""),
            network=requirements.network,
            amount=requirements.amount,
        )

    @staticmethod
    def _hex_to_tron_address(hex_topic: str) -> str:
        """Convert a 32-byte hex topic to a TRON base58 address.

        TRON addresses are stored in event topics as:
        - 24 zero bytes prefix + 8 bytes of the address (last 20 hex chars of the 64-char hex)
        - Convert those 8 bytes (without the 0x41 prefix) to base58 with T prefix
        """
        import base58
        hex_addr = hex_topic.replace("0x", "")[-40:]  # Last 20 bytes = 40 hex chars
        # TRON address: 0x41 + 20-byte hash + 4-byte checksum
        raw = bytes.fromhex("41" + hex_addr)
        # SHA256 twice for checksum
        import hashlib
        h1 = hashlib.sha256(raw).digest()
        h2 = hashlib.sha256(h1).digest()
        checksum = h2[:4]
        address_bytes = raw + checksum
        return base58.b58encode(address_bytes).decode()
