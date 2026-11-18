# Blockchain IQ for LangChain — pay-per-call crypto data over x402

A LangChain tool that buys crypto market data from
[Blockchain IQ](https://www.blockchainiq.co/agents) one call at a time,
paying in USDC on Base through the open **x402** protocol (HTTP 402 +
EIP-3009). No account, no API key — a wallet is the only credential.

**Bounty:** this repository is an entry for the
[Blockchain IQ x402 build bounties](https://www.blockchainiq.co/blog/x402-build-bounties),
**LangChain slot** ("a tool"). It qualifies with a working paid call to one
of the two bounty resources:

| Resource | Path | Price |
| --- | --- | --- |
| Market brief | `GET /api/x402/v1/brief` | **$0.01** |
| Event risk | `GET /api/x402/v1/event-risk` | **$0.05** |

## The tool

`blockchainiq_fetch` (a `StructuredTool`) takes:

- `resource` — a catalogue name (`brief`, `event-risk`, …), a path from the
  free catalogue (`/macro`, `/stablecoins`, …) or a full URL;
- `max_usdc` — a spend guard (default $0.10): the call aborts if the server
  asks for more.

It returns a JSON string: `{resource, paid, amount_usd, settlement, data}`,
where `settlement` is the decoded `PAYMENT-RESPONSE` header (it carries the
settlement transaction hash — the proof a bounty claim needs).

A second tool, `blockchainiq_catalogue`, lists the qualifying resources and
the catalogue URL, and works offline for free.

## How the x402 flow works here

`blockchainiq_x402.py` is a small self-contained x402 v2 client:

1. **Unpaid call.** `GET` the resource with no payment header.
2. **HTTP 402.** The server replies `402 Payment Required` with a base64
   `PAYMENT-REQUIRED` header: `{x402Version: 2, accepts: [...]}`. The Base
   entry is `scheme: "exact"`, `network: "eip155:8453"`, `amount: "10000"`
   (atomic USDC — $0.01 for `brief`), `asset: 0x833589fC…2913` (USDC on
   Base), `payTo: 0x617dA938…7C9e`, and `extra: {name: "USD Coin",
   version: "2"}` — the token's EIP-712 domain fields.
3. **Sign.** The client builds an EIP-3009 `TransferWithAuthorization`
   (from = your wallet, to = `payTo`, value = amount, validity window from
   `maxTimeoutSeconds`, random 32-byte nonce) and signs it as EIP-712 typed
   data with domain `{name: "USD Coin", version: "2", chainId: 8453,
   verifyingContract: <USDC>}`. Signing is offline; nothing is broadcast.
4. **Paid retry.** The request is repeated with the base64 payment payload
   in the `PAYMENT-SIGNATURE` header. A facilitator submits the
   authorization on-chain (gasless for the payer) and the server returns
   `200` with the JSON data and a `PAYMENT-RESPONSE` settlement header.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install .
# or, for a quick run without installing:
pip install langchain-core pydantic requests eth-account
```

## Configure

The signing key comes **only** from the environment:

```bash
export X402_PRIVATE_KEY=0x...   # dedicated wallet, a little USDC on Base
```

Use a dedicated wallet with a small balance, never a main wallet (the same
advice Blockchain IQ gives on its /agents page). The key is never hardcoded,
logged or committed; `.env` is git-ignored (see `.env.example`).

## Run the demo

```bash
python examples/demo.py            # buys the market brief ($0.01)
python examples/demo.py event-risk # buys event risk ($0.05)
```

Or from a LangChain agent:

```python
from blockchainiq_tool import get_tools

tools = get_tools()  # hand to create_agent / AgentExecutor as usual
print(tools[0].invoke({"resource": "brief"}))
```

## Verify locally (no funds, nothing broadcast)

```bash
python scripts/verify_local.py
```

Checks (see `VERIFICATION.md` for recorded output):

- **(a)** the unpaid call to the real endpoint returns 402 and the payment
  requirements parse to the expected amount / asset / network / payTo /
  EIP-712 domain;
- **(b)** a payment payload built from those requirements is a well-formed
  EIP-3009 authorization, signed offline with the public Hardhat test key,
  and the signer recovers correctly — the payload is never sent;
- **(c)** the LangChain tools load, expose their schemas and invoke.

## Claiming the bounty

Make one real paid call with a funded wallet (the demo above), then email
**partnerships@blockchainiq.co** with this repository's link and the
settlement transaction hash from the `PAYMENT-RESPONSE` header. Claims are
checked in email-arrival order; the round closes 31 Dec 2026, 11:59 PM
Central. First passing claim overall is paid $150, the next three $125
each, in USDC on Base.

## License

MIT
