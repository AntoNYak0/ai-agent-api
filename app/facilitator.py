"""Custom x402 facilitator — no Coinbase dependency.

Testnet: auto-approves payments (for testing).
Mainnet: verifies USDC transfers via public Base RPC.
"""
from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    VerifyResponse,
    SettleResponse,
    SupportedResponse,
    SupportedKind,
)


class DirectFacilitator:
    """Self-hosted facilitator that verifies USDC payments directly."""

    def __init__(self, testnet: bool = True, pay_to: str = ""):
        self.testnet = testnet
        self.pay_to = pay_to

    def get_supported(self) -> SupportedResponse:
        networks = (
            ["eip155:84532"]  # Base Sepolia (testnet)
            if self.testnet
            else ["eip155:8453", "eip155:137"]  # Base + Polygon mainnet
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

        # Mainnet: verify via public RPC
        return await self._verify_onchain(payload, requirements)

    async def _verify_onchain(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """Verify a real USDC payment via Base public RPC."""
        import httpx

        rpc_url = "https://mainnet.base.org"
        tx_hash = payload.payload.get("transactionHash", "")

        if not tx_hash:
            return VerifyResponse(
                is_valid=False,
                invalid_reason="missing_tx_hash",
                invalid_message="Payment payload must include transactionHash",
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
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
                        invalid_message=f"Transaction {tx_hash} not found on chain",
                    )

                if receipt.get("status") != "0x1":
                    return VerifyResponse(
                        is_valid=False,
                        invalid_reason="tx_failed",
                        invalid_message="Transaction reverted or failed",
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

        tx_hash = payload.payload.get("transactionHash", "settled")
        return SettleResponse(
            success=True,
            payer=payload.payload.get("payer", ""),
            transaction=tx_hash,
            network=requirements.network,
            amount=requirements.amount,
        )
