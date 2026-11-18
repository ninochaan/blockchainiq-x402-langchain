# Verification — Blockchain IQ x402 for LangChain

Recorded 2026-11-18 on the build VM (Python 3.12.3). Environment: workspace
venv with langchain-core 1.8.2, pydantic 2.12.5, eth-account 0.14.0,
requests 2.34.2.

`scripts/verify_local.py` proves, with **no real funds and nothing
broadcast**: (a) the unpaid call to the real Blockchain IQ endpoint
returns HTTP 402 and the payment requirements parse correctly; (b) the
payment payload is a well-formed EIP-3009 authorization signed **offline**
with the public Hardhat/Anvil test account #0 key (never funded,
test-only) and the signer recovers correctly — the payload is never sent
to the server; (c) the LangChain tools load, expose their schemas and
invoke.

The signed payload is byte-identical across all four framework repos
(same fixed inputs), which cross-checks the Python and TypeScript
implementations against each other.

## Recorded output

```
== (a) Live unpaid probe of the real endpoint ==
[PASS] unpaid GET /brief returns HTTP 402 — status=402
[PASS] x402Version is 2
[PASS] scheme is 'exact'
[PASS] network is eip155:8453 (Base) — eip155:8453
[PASS] amount is 10000 atomic USDC ($0.01) — 10000
[PASS] amount in USD is 0.01
[PASS] asset is USDC on Base — 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
[PASS] payTo matches the catalogue rail — 0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e
[PASS] EIP-712 domain name is 'USD Coin' — USD Coin
[PASS] EIP-712 domain version is '2' — 2
[PASS] EIP-712 chainId is 8453 — 8453
[PASS] EIP-712 verifyingContract is the USDC contract — 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913

== (b) Offline payment-payload construction (test key, never sent) ==
[PASS] payload x402Version is 2
[PASS] payload scheme is 'exact'
[PASS] payload network is eip155:8453
[PASS] authorization.from is the test account — 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
[PASS] authorization.to is payTo
[PASS] authorization.value is 10000
[PASS] validity window is sane — 1799999400 < now < 1800000300
[PASS] signature is 65 bytes hex
[PASS] recovered signer == test account — 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
[PASS] PAYMENT-SIGNATURE header base64 round-trips

Payment payload built offline (signature belongs to the public test key):
{
  "x402Version": 2,
  "scheme": "exact",
  "network": "eip155:8453",
  "payload": {
    "signature": "0x65dd89dd4ec024eec23e109abab3895e5e0580cb4316e01f37ea05ae5a7506d87dee41a58fd68fb715c468caac8c67130ee14f2fc130de0cc6e3110f8390cc1c1c",
    "authorization": {
      "from": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
      "to": "0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e",
      "value": "10000",
      "validAfter": "1799999400",
      "validBefore": "1800000300",
      "nonce": "0x1111111111111111111111111111111111111111111111111111111111111111"
    }
  }
}

== (c) LangChain wiring ==
[PASS] two tools are provided — ['blockchainiq_fetch', 'blockchainiq_catalogue']
[PASS] tool name is blockchainiq_fetch
[PASS] tool schema exposes 'resource' — ['resource', 'max_usdc']
[PASS] tool schema exposes 'max_usdc'
[PASS] catalogue tool invokes offline

RESULT: PASS (all checks)
```
