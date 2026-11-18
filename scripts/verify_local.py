#!/usr/bin/env python3
"""Local verification for the Blockchain IQ x402 LangChain integration.

Proves, WITHOUT spending real funds and without broadcasting anything:

(a) an unpaid call to the real Blockchain IQ endpoint returns HTTP 402 and
    the client parses the payment requirements correctly (amount, asset,
    network, payTo, EIP-712 domain fields);
(b) the payment payload built from those requirements is a well-formed
    EIP-3009 authorization, signed OFFLINE with the public Hardhat/Anvil
    test account #0 key (a well-known, never-funded test key) — the signer
    is recovered from the signature and matched; the payload is never sent;
(c) the LangChain wiring loads: the tools construct, expose their schemas
    and the (free, offline) catalogue tool invokes.

Exit code 0 means every check passed.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blockchainiq_x402 import (  # noqa: E402
    BASE_URL,
    build_payment_payload,
    eip712_domain,
    get_payment_requirements,
    recover_authorization_signer,
    requirement_amount_usd,
    select_evm_requirement,
)

# Public Hardhat/Anvil test account #0 — test-only, never funded.
TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
EXPECTED = {
    "amount": "10000",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "network": "eip155:8453",
    "payTo": "0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e",
    "domain_name": "USD Coin",
    "domain_version": "2",
    "chain_id": 8453,
}

failures = []


def check(label, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    print("== (a) Live unpaid probe of the real endpoint ==")
    status, payment_required, _resp = get_payment_requirements(BASE_URL + "/brief")
    check("unpaid GET /brief returns HTTP 402", status == 402, f"status={status}")
    if payment_required is None:
        check("PAYMENT-REQUIRED header present", False)
        return 1
    check("x402Version is 2", payment_required.get("x402Version") == 2)

    req = select_evm_requirement(payment_required)
    check("scheme is 'exact'", req.get("scheme") == "exact")
    check("network is eip155:8453 (Base)", req.get("network") == EXPECTED["network"], req.get("network"))
    check("amount is 10000 atomic USDC ($0.01)", req.get("amount") == EXPECTED["amount"], req.get("amount"))
    check("amount in USD is 0.01", abs(requirement_amount_usd(req) - 0.01) < 1e-12)
    check("asset is USDC on Base", req.get("asset") == EXPECTED["asset"], req.get("asset"))
    check("payTo matches the catalogue rail", req.get("payTo") == EXPECTED["payTo"], req.get("payTo"))

    domain = eip712_domain(req)
    check("EIP-712 domain name is 'USD Coin'", domain["name"] == EXPECTED["domain_name"], domain["name"])
    check("EIP-712 domain version is '2'", domain["version"] == EXPECTED["domain_version"], domain["version"])
    check("EIP-712 chainId is 8453", domain["chainId"] == EXPECTED["chain_id"], str(domain["chainId"]))
    check(
        "EIP-712 verifyingContract is the USDC contract",
        domain["verifyingContract"] == EXPECTED["asset"],
        domain["verifyingContract"],
    )

    print("\n== (b) Offline payment-payload construction (test key, never sent) ==")
    payload = build_payment_payload(
        payment_required,
        TEST_KEY,
        now=1_800_000_000,
        nonce="0x" + "11" * 32,
    )
    check("payload x402Version is 2", payload["x402Version"] == 2)
    check("payload scheme is 'exact'", payload["scheme"] == "exact")
    check("payload network is eip155:8453", payload["network"] == EXPECTED["network"])
    auth = payload["payload"]["authorization"]
    sig = payload["payload"]["signature"]
    check("authorization.from is the test account", auth["from"] == TEST_ADDRESS, auth["from"])
    check("authorization.to is payTo", auth["to"] == EXPECTED["payTo"])
    check("authorization.value is 10000", auth["value"] == "10000")
    check(
        "validity window is sane",
        int(auth["validAfter"]) < 1_800_000_000 < int(auth["validBefore"]),
        f"{auth['validAfter']} < now < {auth['validBefore']}",
    )
    check("signature is 65 bytes hex", len(bytes.fromhex(sig.removeprefix('0x'))) == 65)
    recovered = recover_authorization_signer(req, auth, sig)
    check("recovered signer == test account", recovered == TEST_ADDRESS, recovered)
    header_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    roundtrip = json.loads(base64.b64decode(header_b64))
    check("PAYMENT-SIGNATURE header base64 round-trips", roundtrip == payload)
    print("\nPayment payload built offline (signature belongs to the public test key):")
    print(json.dumps(payload, indent=2))

    print("\n== (c) LangChain wiring ==")
    from blockchainiq_tool import blockchainiq_catalogue, blockchainiq_fetch, get_tools

    tools = get_tools()
    check("two tools are provided", len(tools) == 2, f"{[t.name for t in tools]}")
    check("tool name is blockchainiq_fetch", blockchainiq_fetch.name == "blockchainiq_fetch")
    schema_props = blockchainiq_fetch.args_schema.model_json_schema().get("properties", {})
    check("tool schema exposes 'resource'", "resource" in schema_props, f"{list(schema_props)}")
    check("tool schema exposes 'max_usdc'", "max_usdc" in schema_props)
    out = blockchainiq_catalogue.invoke({})
    check("catalogue tool invokes offline", isinstance(out, str) and "brief" in out)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s) failed)")
        return 1
    print("RESULT: PASS (all checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
