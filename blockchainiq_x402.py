"""Minimal x402 v2 client core for the Blockchain IQ data API.

Implements the "exact" payment scheme on EVM (Base, eip155:8453) with USDC
paid via an EIP-3009 ``transferWithAuthorization`` signature:

1. GET a paid resource with no payment header.
2. The server answers HTTP 402 with a base64 ``PAYMENT-REQUIRED`` header
   naming the scheme, network, amount, asset, payTo address and the EIP-712
   domain fields (``extra.name`` / ``extra.version``) of the token.
3. This module parses those requirements, builds an EIP-3009 authorization,
   signs it with the key from the ``X402_PRIVATE_KEY`` environment variable
   and retries the request with a base64 ``PAYMENT-SIGNATURE`` header.
4. The server settles gaslessly (a facilitator submits the authorization)
   and returns the JSON data plus a ``PAYMENT-RESPONSE`` header carrying the
   settlement proof (transaction hash).

Only the Python standard library, ``requests`` and ``eth-account`` are used.
The private key is read from the environment at runtime only; it is never
stored, logged or committed.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

BASE_URL = "https://www.blockchainiq.co/api/x402/v1"
EVM_NETWORK = "eip155:8453"  # Base mainnet
PAYMENT_REQUIRED_HEADER = "PAYMENT-REQUIRED"
PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"
PAYMENT_RESPONSE_HEADER = "PAYMENT-RESPONSE"
PRIVATE_KEY_ENV = "X402_PRIVATE_KEY"
USDC_DECIMALS = 6

# The two resources a Blockchain IQ build-bounty claim may call
# (https://www.blockchainiq.co/agents, "Bounties" section).
QUALIFYING_RESOURCES = {
    "brief": {"path": "/brief", "price_usd": 0.01},
    "event-risk": {"path": "/event-risk", "price_usd": 0.05},
}

TRANSFER_WITH_AUTHORIZATION_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}


class X402Error(RuntimeError):
    """Raised when the x402 flow cannot be completed."""


@dataclass
class FetchResult:
    """Outcome of a (possibly paid) Blockchain IQ call."""

    status_code: int
    data: Any
    paid: bool = False
    amount_usd: Optional[float] = None
    settlement: Optional[dict] = None  # decoded PAYMENT-RESPONSE header
    payment_payload: Optional[dict] = None  # what was signed and sent
    raw_headers: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Payment-requirements parsing
# --------------------------------------------------------------------------

def decode_payment_required(header_value: str) -> dict:
    """Decode the base64 ``PAYMENT-REQUIRED`` header of an HTTP 402 reply."""
    try:
        return json.loads(base64.b64decode(header_value).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise X402Error(f"Could not decode PAYMENT-REQUIRED header: {exc}") from exc


def select_evm_requirement(payment_required: dict, network: str = EVM_NETWORK) -> dict:
    """Pick the ``exact`` / EVM (Base) entry from the 402 ``accepts`` list."""
    for req in payment_required.get("accepts", []):
        if req.get("scheme") == "exact" and req.get("network") == network:
            return req
    raise X402Error(
        f"No 'exact' requirement for network {network} in the 402 response; "
        f"got networks: {[r.get('network') for r in payment_required.get('accepts', [])]}"
    )


def eip712_domain(requirement: dict) -> dict:
    """EIP-712 domain of the payment token, taken from the 402 requirement.

    For USDC on Base this is
    ``{name: "USD Coin", version: "2", chainId: 8453, verifyingContract: <USDC>}``.
    The name/version come from ``extra`` in the requirement, the chain id from
    the CAIP-2 network string and the contract from ``asset``.
    """
    extra = requirement.get("extra") or {}
    chain_id = int(str(requirement["network"]).split(":")[-1])
    return {
        "name": extra.get("name"),
        "version": extra.get("version"),
        "chainId": chain_id,
        "verifyingContract": requirement["asset"],
    }


def requirement_amount_usd(requirement: dict) -> float:
    """Human USD amount of a requirement (USDC has 6 decimals)."""
    return int(requirement["amount"]) / (10 ** USDC_DECIMALS)


# --------------------------------------------------------------------------
# EIP-3009 authorization: build + sign (works fully offline)
# --------------------------------------------------------------------------

def build_authorization(
    requirement: dict,
    from_address: str,
    now: Optional[int] = None,
    nonce: Optional[str] = None,
) -> dict:
    """Build the EIP-3009 ``TransferWithAuthorization`` message (string values)."""
    now = int(time.time()) if now is None else now
    max_timeout = int(requirement.get("maxTimeoutSeconds", 300))
    return {
        "from": from_address,
        "to": requirement["payTo"],
        "value": str(requirement["amount"]),
        "validAfter": str(max(0, now - 600)),
        "validBefore": str(now + max_timeout),
        "nonce": nonce or ("0x" + secrets.token_hex(32)),
    }


def _signing_message(authorization: dict) -> dict:
    """Convert the string-valued authorization to typed-data message values."""
    return {
        "from": authorization["from"],
        "to": authorization["to"],
        "value": int(authorization["value"]),
        "validAfter": int(authorization["validAfter"]),
        "validBefore": int(authorization["validBefore"]),
        "nonce": bytes.fromhex(authorization["nonce"].removeprefix("0x")),
    }


def sign_authorization(requirement: dict, authorization: dict, private_key: str) -> str:
    """Sign the authorization with EIP-712; returns the hex signature."""
    signable = encode_typed_data(
        domain_data=eip712_domain(requirement),
        message_types=TRANSFER_WITH_AUTHORIZATION_TYPES,
        message_data=_signing_message(authorization),
    )
    signed = Account.sign_message(signable, private_key=private_key)
    return "0x" + signed.signature.hex().removeprefix("0x")


def build_payment_payload(
    payment_required: dict,
    private_key: str,
    now: Optional[int] = None,
    nonce: Optional[str] = None,
) -> dict:
    """Full x402 v2 payment payload for the EVM ``exact`` requirement."""
    requirement = select_evm_requirement(payment_required)
    account = Account.from_key(private_key)
    authorization = build_authorization(requirement, account.address, now=now, nonce=nonce)
    signature = sign_authorization(requirement, authorization, private_key)
    return {
        "x402Version": int(payment_required.get("x402Version", 2)),
        "scheme": requirement["scheme"],
        "network": requirement["network"],
        "payload": {
            "signature": signature,
            "authorization": authorization,
        },
    }


def encode_payment_header(payload: dict) -> str:
    """Base64-encode a payment payload for the PAYMENT-SIGNATURE header."""
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def recover_authorization_signer(
    requirement: dict, authorization: dict, signature: str
) -> str:
    """Recover the signer of an authorization (used by offline verification)."""
    signable = encode_typed_data(
        domain_data=eip712_domain(requirement),
        message_types=TRANSFER_WITH_AUTHORIZATION_TYPES,
        message_data=_signing_message(authorization),
    )
    return Account.recover_message(signable, signature=signature)


# --------------------------------------------------------------------------
# HTTP flow
# --------------------------------------------------------------------------

def get_payment_requirements(
    url: str, session: Optional[requests.Session] = None, timeout: int = 30
) -> tuple[int, Optional[dict], requests.Response]:
    """Unpaid probe: returns (status, decoded PAYMENT-REQUIRED or None, response)."""
    http = session or requests
    resp = http.get(url, timeout=timeout)
    header = resp.headers.get(PAYMENT_REQUIRED_HEADER) or resp.headers.get(
        "Payment-Required"
    )
    parsed = decode_payment_required(header) if header else None
    return resp.status_code, parsed, resp


def resource_url(resource: str) -> str:
    """Accept a resource name ('brief'), a path ('/brief') or a full URL."""
    if resource.startswith("http://") or resource.startswith("https://"):
        return resource
    if resource in QUALIFYING_RESOURCES:
        return BASE_URL + QUALIFYING_RESOURCES[resource]["path"]
    return BASE_URL + (resource if resource.startswith("/") else "/" + resource)


def fetch_paid_resource(
    resource: str,
    private_key: Optional[str] = None,
    max_amount_usd: Optional[float] = None,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
) -> FetchResult:
    """Fetch a Blockchain IQ resource, paying through x402 if it is paid.

    ``private_key`` defaults to the ``X402_PRIVATE_KEY`` environment variable
    and is only needed when the resource answers 402. ``max_amount_usd`` is a
    spend guard: the call aborts if the 402 asks for more than that.
    """
    url = resource_url(resource)
    http = session or requests

    first = http.get(url, timeout=timeout)
    if first.status_code == 200:
        return FetchResult(
            status_code=200, data=first.json(), paid=False,
            raw_headers=dict(first.headers),
        )
    if first.status_code != 402:
        raise X402Error(
            f"Unexpected status {first.status_code} from {url}: {first.text[:200]}"
        )

    header = first.headers.get(PAYMENT_REQUIRED_HEADER)
    if not header:
        raise X402Error("HTTP 402 without a PAYMENT-REQUIRED header")
    payment_required = decode_payment_required(header)
    requirement = select_evm_requirement(payment_required)
    amount_usd = requirement_amount_usd(requirement)
    if max_amount_usd is not None and amount_usd > max_amount_usd:
        raise X402Error(
            f"Refusing to pay ${amount_usd:.2f} for {url}: above the "
            f"${max_amount_usd:.2f} per-call cap"
        )

    key = private_key or os.environ.get(PRIVATE_KEY_ENV)
    if not key:
        raise X402Error(
            f"No signing key: set the {PRIVATE_KEY_ENV} environment variable "
            "(a dedicated wallet holding a little USDC on Base)"
        )

    payload = build_payment_payload(payment_required, key)
    paid_resp = http.get(
        url,
        headers={PAYMENT_SIGNATURE_HEADER: encode_payment_header(payload)},
        timeout=timeout,
    )
    if paid_resp.status_code != 200:
        raise X402Error(
            f"Paid retry failed with status {paid_resp.status_code}: "
            f"{paid_resp.text[:200]}"
        )

    settlement = None
    resp_header = paid_resp.headers.get(PAYMENT_RESPONSE_HEADER)
    if resp_header:
        try:
            settlement = json.loads(base64.b64decode(resp_header).decode("utf-8"))
        except Exception:
            settlement = {"raw": resp_header}

    return FetchResult(
        status_code=200,
        data=paid_resp.json(),
        paid=True,
        amount_usd=amount_usd,
        settlement=settlement,
        payment_payload=payload,
        raw_headers=dict(paid_resp.headers),
    )
