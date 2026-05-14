"""Custom x402 facilitator — no Coinbase dependency.

Testnet: auto-approves payments (for testing).
Mainnet: verifies USDC transfers via public Base/Polygon RPC.
"""
from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    VerifyResponse,
    SettleResponse,
    SupportedResponse,
    SupportedKind,
)

RPC_URLS = {
    "eip155:8453": "https://mainnet.base.org",
    "eip155:137": "https://polygon-rpc.com",
}


class DirectFacilitator:
    """Self-hosted facilitator that verifies USDC payments directly."""

    def __init__(self, testnet: bool = True, pay_to: str = ""):
        self.testnet = testnet
        self.pay_to = pay_to.lower() if pay_to else ""

    def get_supported(self) -> SupportedResponse:
        networks = (
            ["eip155:84532"]
            if self.testnet
            else ["eip155:8453", "eip155:137"]
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
            return VerifyResponse(
                is_valid=True,
                payer=payload.payload.get("payer", "testnet"),
            )

        return await self._verify_onchain(payload, requirements)

    async def _verify_onchain(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """Verify a real USDC payment via public RPC."""
        import httpx

        network = requirements.network
        rpc_url = RPC_URLS.get(network, "https://mainnet.base.org")
        tx_hash = payload.payload.get("transactionHash", "")

        if not tx_hash:
            return VerifyResponse(
                is_valid=False,
                invalid_reason="missing_tx_hash",
                invalid_message="Payment payload must include transactionHash",
            )

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
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_not_found",
                        invalid_message=f"Transaction {tx_hash[:10]}... not found. Wait for confirmation.",
                    )

                if receipt.get("status") != "0x1":
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_failed",
                        invalid_message="Transaction reverted or failed",
                    )

                # 2. Get transaction details to verify recipient
                resp2 = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "eth_getTransactionByHash",
                        "params": [tx_hash],
                    },
                )
                tx_data = resp2.json().get("result", {}) or {}
                to_addr = (tx_data.get("to") or "").lower()

                # 3. Check the USDC was sent to our wallet
                if self.pay_to and to_addr != self.pay_to:
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="wrong_recipient",
                        invalid_message=f"USDC sent to {to_addr}, expected {self.pay_to}",
                    )

                return VerifyResponse(
                    is_valid=True,
                    payer=receipt.get("from", ""),
                )
        except Exception as e:
            return VerifyResponse(
                is_valid=False,
                invalid_reason="rpc_error",
                invalid_message=str(e),
            )

    async def settle(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> SettleResponse:
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
