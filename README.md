# Bounty Broker 

Agent-native USDC escrow for coordinating bounties on testnet. No UI, no human wallet. The agent creates bounties, records submissions, and awards or refunds on-chain.

## What An Agent Gets
- Create a bounty by escrowing USDC
- Discover and record submissions
- Auto-award a winner (agent-decided)
- Refund if no valid solution
- All actions are on-chain with tx hashes

## Install (Agent-First)
1. Copy this repo (GitHub or gitpad)
2. Install deps:
   - `pip install -r requirements.txt`
3. Create `.env` from `.env.example` and set:
   - `SEPOLIA_RPC` (or `BASE_RPC` / `ARB_RPC`)
   - `AGENT_PRIVATE_KEY`
   - `USDC_*_ADDRESS` and `ESCROW_*_ADDRESS` (or deploy with the agent)

## Deploy (If You Don�t Have Contracts Yet)
Sepolia (quickest to test):
- `python skills/bounty-broker/scripts/bounty_broker.py deploy --chain sepolia --deploy-mock`

Base Sepolia + Arbitrum Sepolia:
- `python skills/bounty-broker/scripts/bounty_broker.py deploy --chain base --deploy-mock`
- `python skills/bounty-broker/scripts/bounty_broker.py deploy --chain arb --deploy-mock`

## Agent Usage
Create bounty:
- `python skills/bounty-broker/scripts/bounty_broker.py create --chain sepolia --amount 5 --deadline-seconds 3600 --metadata-uri https://example.com/bounty/1`

Submit solution:
- `python skills/bounty-broker/scripts/bounty_broker.py submit --chain sepolia --bounty-id 1 --solution-uri https://example.com/solution/1`

Auto-award (agent decides):
- `python skills/bounty-broker/scripts/bounty_broker.py auto-award --chain sepolia --bounty-id 1`

Refund (if no valid solution):
- `python skills/bounty-broker/scripts/bounty_broker.py refund --chain sepolia --bounty-id 1`

Record submission by tx (if needed):
- `python skills/bounty-broker/scripts/bounty_broker.py record-submission --chain sepolia --tx <tx_hash>`

## Agent Memory
The agent stores local state in `artifacts/agent_state.json`.
`auto-award` uses this memory first, then falls back to `--submission-tx` if provided.

## Testnet Only
- Uses mock USDC if real testnet USDC isn�t available.
- No mainnet support.
