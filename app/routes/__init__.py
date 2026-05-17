"""Shared route helpers — imported by all route modules."""

from fastapi import Request


def get_network(request: Request) -> str:
    try:
        return request.state.payment_requirements.network
    except AttributeError:
        return "unknown"


def get_tx(request: Request) -> str:
    try:
        return request.state.payment_payload.transaction
    except AttributeError:
        return "unknown"
