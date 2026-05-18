"""Custom x402 facilitator — no Coinbase dependency.

Testnet: auto-approves payments (for testing).
Mainnet: verifies USDC transfers via public Base/Polygon RPC.
"""
import logging

from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    VerifyResponse,
    SettleResponse,
    SupportedResponse,
    SupportedKind,
)

logger = logging.getLogger("facilitator")

RPC_URLS = {
    "eip155:8453": "https://mainnet.base.org",
    "eip155:42161": "https://arb1.arbitrum.io/rpc",
    "eip155:10": "https://mainnet.optimism.io",
    "eip155:84532": "https://sepolia.base.org",
    "eip155:421614": "https://sepolia-rollup.arbitrum.io/rpc",
    "eip155:11155420": "https://sepolia.optimism.io",
}

# USDC contract addresses by CAIP-2 network
USDC_CONTRACTS = {
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # Base mainnet
    "eip155:42161": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # Arbitrum mainnet
    "eip155:10": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",     # Optimism mainnet
    "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia testnet
    "eip155:421614": "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4dD",  # Arbitrum Sepolia testnet
    "eip155:11155420": "0x5fd84259d66Cd46123540766Be93DFE6D43130D7",  # Optimism Sepolia testnet
}

# keccak256("Transfer(address,address,uint256)")
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class DirectFacilitator:
    """Self-hosted facilitator that verifies USDC payments directly."""

    def __init__(self, testnet: bool = True, pay_to: str = ""):
        self.testnet = testnet
        self.pay_to = pay_to.lower() if pay_to else ""

    def get_supported(self) -> SupportedResponse:
        networks = (
            ["eip155:84532", "eip155:421614", "eip155:11155420"]
            if self.testnet
            else ["eip155:8453", "eip155:42161", "eip155:10"]
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
            logger.info(
                "Testnet auto-approve: tx=%s tool=%s",
                payload.payload.get("transactionHash", "no-tx")[:16],
                payload.payload.get("payer", "testnet"),
            )
            return VerifyResponse(
                is_valid=True,
                payer=payload.payload.get("payer", "testnet"),
            )

        return await self._verify_onchain_evm(payload, requirements)

    async def _verify_onchain_evm(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """Verify a real USDC payment via public RPC with amount + contract checks."""
        import httpx

        network = requirements.network
        rpc_url = RPC_URLS.get(network, "https://mainnet.base.org")
        tx_hash = payload.payload.get("transactionHash", "")

        if not tx_hash:
            logger.warning("Verification rejected: missing transactionHash")
            return VerifyResponse(
                is_valid=False,
                invalid_reason="missing_tx_hash",
                invalid_message="Payment payload must include transactionHash",
            )

        # Verify we support this network
        expected_contract = USDC_CONTRACTS.get(network)
        if not expected_contract:
            logger.warning("Verification rejected: unsupported network %s", network)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="unsupported_network",
                invalid_message=f"Network {network} not supported. Use Base (eip155:8453), Arbitrum (eip155:42161), or Optimism (eip155:10)",
            )

        logger.info("Verifying tx %s... on %s", tx_hash[:16], network)

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # 1. Get transaction receipt
                resp = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_getTransactionReceipt",
                        "params": [tx_hash],
                    },
                )
                data = resp.json()
                receipt = data.get("result")

                if not receipt:
                    logger.warning("Tx %s... not found on chain", tx_hash[:16])
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_not_found",
                        invalid_message=f"Transaction {tx_hash[:10]}... not found on chain. Wait for confirmation.",
                    )

                if receipt.get("status") != "0x1":
                    logger.warning("Tx %s... reverted (status=%s)", tx_hash[:16], receipt.get("status"))
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_failed",
                        invalid_message="Transaction reverted or failed",
                    )

                # 2. Find the USDC Transfer event in logs (match contract + topic)
                expected_contract_lower = expected_contract.lower()
                transfer_amount = None
                transfer_recipient = None

                for log in receipt.get("logs", []):
                    topics = log.get("topics", [])
                    log_address = log.get("address", "").lower()

                    if topics and topics[0] == TRANSFER_EVENT_TOPIC:
                        # Must be the expected USDC contract, not some other ERC-20
                        if log_address != expected_contract_lower:
                            continue

                        # topics[1] = from (indexed), topics[2] = to (indexed)
                        if len(topics) >= 3:
                            transfer_recipient = "0x" + topics[2][-40:]

                        # data contains uint256 amount
                        log_data = log.get("data", "0x")
                        if log_data and log_data != "0x":
                            transfer_amount = int(log_data, 16)

                        break  # Found our USDC Transfer

                if transfer_recipient is None:
                    logger.warning(
                        "Tx %s... no USDC Transfer from %s. Log count: %d",
                        tx_hash[:16], expected_contract, len(receipt.get("logs", [])),
                    )
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="no_usdc_transfer",
                        invalid_message=f"No USDC Transfer event from contract {expected_contract} found in transaction logs",
                    )

                # 3. Check recipient
                transfer_recipient_lower = transfer_recipient.lower()
                if self.pay_to and transfer_recipient_lower != self.pay_to:
                    logger.warning(
                        "Tx %s... wrong recipient: got %s, expected %s",
                        tx_hash[:16], transfer_recipient, self.pay_to,
                    )
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
                        logger.warning(
                            "Tx %s... insufficient amount: got %.4f USDC, need %.4f USDC",
                            tx_hash[:16],
                            transfer_amount / 1e6,
                            required_amount / 1e6,
                        )
                        return VerifyResponse(
                            is_valid=False,
                            invalid_reason="insufficient_amount",
                            invalid_message=(
                                f"Payment insufficient: got {transfer_amount / 1e6:.4f} USDC, "
                                f"required at least {required_amount / 1e6:.4f} USDC"
                            ),
                        )

                logger.info(
                    "Payment verified: tx=%s... payer=%s amount=%.4f USDC",
                    tx_hash[:16],
                    receipt.get("from", "")[:10],
                    transfer_amount / 1e6 if transfer_amount else 0,
                )
                return VerifyResponse(
                    is_valid=True,
                    payer=receipt.get("from", ""),
                )
        except Exception as e:
            logger.error("RPC verification failed for tx %s...: %s", tx_hash[:16], e)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="rpc_error",
                invalid_message=f"Payment verification failed: {e}",
            )

    async def settle(self, payload: PaymentPayload) -> SettleResponse:
        requirements = payload.accepted
        if self.testnet:
            return SettleResponse(
                success=True,
                payer=payload.payload.get("payer", "testnet"),
                transaction=payload.payload.get("transactionHash", "testnet-tx"),
                network=requirements.network,
                amount=requirements.amount,
            )

        return SettleResponse(
            success=True,
            payer=payload.payload.get("payer", ""),
            transaction=payload.payload.get("transactionHash", ""),
            network=requirements.network,
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

        logger.info("Verifying TRC-20 tx %s... on TRON", tx_hash[:16])

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # 1. Get transaction events from TronGrid
                url = f"{TRONGRID_API}/v1/transactions/{tx_hash}/events"
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning("TronGrid error: %s", resp.status_code)
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_not_found",
                        invalid_message=f"Transaction {tx_hash[:10]}... not found on TRON. Wait for confirmation.",
                    )

                events_data = resp.json()
                events = events_data.get("data", [])

                if not events:
                    logger.warning("Tx %s... no events found on TRON", tx_hash[:16])
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_not_found",
                        invalid_message=f"Transaction {tx_hash[:10]}... not found on TRON.",
                    )

                # 2. Find USDT TRC-20 Transfer event
                transfer_amount = None
                transfer_recipient = None

                for event in events:
                    # TRC-20 Transfer: event_name is not always present; check contract + topic
                    contract = event.get("contract_address", event.get("contract", ""))
                    if contract != USDT_TRC20_CONTRACT:
                        continue

                    # In TronGrid v1 events API:
                    # topic0 = event signature hash
                    # result contains decoded indexed params: from, to, value
                    result = event.get("result", {})
                    # Try multiple field names used by TronGrid
                    to_addr = result.get("to", result.get("_to", ""))
                    value_str = result.get("value", result.get("_value", "0"))

                    if to_addr:
                        transfer_recipient = to_addr
                    if value_str:
                        transfer_amount = int(str(value_str))

                    # Also check raw topics for the Transfer signature
                    raw_topics = event.get("raw_data", {}).get("topics", event.get("topics", []))
                    if raw_topics and raw_topics[0] == TRC20_TRANSFER_TOPIC:
                        if len(raw_topics) >= 3:
                            # topics[1] = from, topics[2] = to (both 32-byte hex)
                            transfer_recipient = TronFacilitator._hex_to_tron_address(raw_topics[2])
                        # Value is in the raw data field
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
            logger.error("TRON verification failed for tx %s...: %s", tx_hash[:16], e)
            return VerifyResponse(
                is_valid=False,
                invalid_reason="tron_rpc_error",
                invalid_message=f"TRON payment verification failed: {e}",
            )

    async def settle(self, payload: PaymentPayload) -> SettleResponse:
        requirements = payload.accepted
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
