"""LangChain tool for Blockchain IQ's pay-per-call x402 API.

Exposes one tool, ``blockchainiq_fetch``, that an LLM agent can call to buy
crypto market data from Blockchain IQ (https://www.blockchainiq.co/agents).
The tool handles the whole x402 v2 flow itself: unpaid call, HTTP 402,
EIP-3009 USDC (Base) payment authorization signed with the key in the
``X402_PRIVATE_KEY`` environment variable, paid retry, JSON data back.

Bounty: Blockchain IQ x402 build bounties, LangChain slot — a public repo
with a working paid call to ``brief`` ($0.01) or ``event-risk`` ($0.05).
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from blockchainiq_x402 import (
    BASE_URL,
    QUALIFYING_RESOURCES,
    fetch_paid_resource,
)


class BlockchainIqFetchInput(BaseModel):
    """Arguments of the blockchainiq_fetch tool."""

    resource: str = Field(
        default="brief",
        description=(
            "Blockchain IQ resource to fetch: a catalogue name such as "
            "'brief' (market brief, $0.01) or 'event-risk' (scheduled "
            "market-moving events, $0.05), any other path from the free "
            f"catalogue at {BASE_URL} (e.g. '/macro', '/stablecoins'), or a "
            "full URL. Paid resources are paid automatically through x402."
        ),
    )
    max_usdc: float = Field(
        default=0.10,
        description=(
            "Spend guard: refuse to pay if the resource costs more than this "
            "many USDC in a single call."
        ),
    )


def _fetch(resource: str = "brief", max_usdc: float = 0.10) -> str:
    result = fetch_paid_resource(resource, max_amount_usd=max_usdc)
    return json.dumps(
        {
            "resource": resource,
            "paid": result.paid,
            "amount_usd": result.amount_usd,
            "settlement": result.settlement,
            "data": result.data,
        }
    )


def _describe_resources() -> str:
    lines = [f"Blockchain IQ catalogue (free): {BASE_URL}", "Bounty-qualifying resources:"]
    for name, info in QUALIFYING_RESOURCES.items():
        lines.append(f"  - {name}: {info['path']} (${info['price_usd']:.2f} per call)")
    return "\n".join(lines)


blockchainiq_fetch = StructuredTool.from_function(
    func=_fetch,
    name="blockchainiq_fetch",
    description=(
        "Fetch crypto market data from Blockchain IQ, paying per call in USDC "
        "on Base through the x402 protocol when the resource is paid. Use "
        "'brief' for a $0.01 market brief (BTC/ETH/SOL/XRP prices, 48h "
        "events, risk flags) or 'event-risk' for $0.05 scheduled market-moving "
        "events. The signing key comes from the X402_PRIVATE_KEY environment "
        "variable. Returns a JSON string with the data and, for paid calls, "
        "the settlement proof."
    ),
    args_schema=BlockchainIqFetchInput,
)

blockchainiq_catalogue = StructuredTool.from_function(
    func=_describe_resources,
    name="blockchainiq_catalogue",
    description=(
        "List the Blockchain IQ resources that qualify for a paid x402 call "
        "and the URL of the free full catalogue."
    ),
)


def get_tools() -> list:
    """All LangChain tools provided by this integration."""
    return [blockchainiq_fetch, blockchainiq_catalogue]


if __name__ == "__main__":  # tiny smoke run without an LLM
    print(blockchainiq_catalogue.invoke({}))
