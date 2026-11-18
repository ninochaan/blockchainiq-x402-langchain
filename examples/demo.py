#!/usr/bin/env python3
"""Demo: buy the Blockchain IQ market brief through x402 with LangChain.

Usage:
    export X402_PRIVATE_KEY=0x...   # dedicated wallet, a little USDC on Base
    python examples/demo.py [resource]

With no argument it fetches 'brief' ($0.01). 'event-risk' ($0.05) also works.
The demo invokes the LangChain tool directly (no LLM needed); in an agent,
hand ``get_tools()`` to any LangChain agent executor instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blockchainiq_tool import blockchainiq_fetch  # noqa: E402


def main() -> None:
    resource = sys.argv[1] if len(sys.argv) > 1 else "brief"
    print(f"Fetching '{resource}' via the blockchainiq_fetch LangChain tool...")
    out = blockchainiq_fetch.invoke({"resource": resource, "max_usdc": 0.10})
    print(out)


if __name__ == "__main__":
    main()
