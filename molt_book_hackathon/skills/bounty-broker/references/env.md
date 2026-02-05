# Environment Variables

Set these in the repo root `.env`:

- `SEPOLIA_RPC`: Ethereum Sepolia RPC URL (optional if using Base/Arb only)
- `BASE_SEPOLIA_RPC`: Base Sepolia RPC URL
- `ARB_SEPOLIA_RPC`: Arbitrum Sepolia RPC URL
- `AGENT_PRIVATE_KEY`: testnet-only key used by the agent
- `USDC_SEPOLIA_ADDRESS`: real USDC on Ethereum Sepolia if available, otherwise leave empty to deploy MockUSDC
- `USDC_BASE_ADDRESS`: real USDC on Base Sepolia if available, otherwise leave empty to deploy MockUSDC
- `USDC_ARB_ADDRESS`: real USDC on Arbitrum Sepolia if available, otherwise leave empty to deploy MockUSDC
- `ESCROW_SEPOLIA_ADDRESS`: set after deploy
- `ESCROW_BASE_ADDRESS`: set after deploy
- `ESCROW_ARB_ADDRESS`: set after deploy

- `MOLTBOOK_BASE`: Moltbook API base URL (default https://www.moltbook.com/api/v1)
- `MOLTBOOK_API_KEY`: API key for agent posting/voting
- `REPO_URL`: Repo link for submission (GitHub or gitpad)
