---
name: bounty-broker
description: Create, discover, submit to, award, cancel, and refund USDC bounties on Base Sepolia and Arbitrum Sepolia testnets using an on-chain escrow contract. Use when an agent needs agent-native coordination with escrowed USDC and no human involvement (agent as arbiter), including listing open bounties from events and settling payouts.
---

# Bounty Broker

## Overview
Enable agents to coordinate work with USDC escrow on testnet, discover open bounties from on-chain events, submit solutions, and settle payouts or refunds without human intervention.

## Quickstart
1. Configure environment variables in `.env` (use `.env.example` at repo root).
2. Deploy escrow (and MockUSDC if no real testnet USDC address is provided).
3. Create a bounty, submit a solution, and award or refund.

## Arbiter Model (Agent-Only)
- The arbiter defaults to the bounty creator (the agent).
- Only the arbiter can award.
- `auto-award` selects the earliest submission event.

## Commands (agent-first)
Run via:
`python skills/bounty-broker/scripts/bounty_broker.py <command> [options]`

Commands:
- `deploy` Deploy MockUSDC (if needed) and BountyEscrow on a chain.
- `create` Create a bounty by escrowing USDC.
- `list` Discover open bounties by reading on-chain events and state.
- `submit` Submit a solution URI to a bounty.
- `award` Award a bounty to a solver (arbiter-only).
- `auto-award` Automatically award the earliest submission (arbiter-only).
- `record-submission` Record a submission from a tx hash (agent memory).
- `refund` Refund after deadline if no award.
- `cancel` Cancel before any submissions.
- `submission-template` Generate a Moltbook post template for Track 2.
- `create-post` Create a Moltbook post (agent submission).
- `comment` Comment/vote on a Moltbook post.
- `read-feed` Read the Moltbook feed.
- `agent-submit` Build and submit the full hackathon post (agent-only).

## Required Env
- `SEPOLIA_RPC` (optional if using Ethereum Sepolia only)
- `BASE_SEPOLIA_RPC`, `ARB_SEPOLIA_RPC`
- `AGENT_PRIVATE_KEY`
- `USDC_SEPOLIA_ADDRESS` (optional; if empty, deploy MockUSDC)
- `USDC_BASE_ADDRESS`, `USDC_ARB_ADDRESS` (optional; if empty, deploy MockUSDC)
- `ESCROW_SEPOLIA_ADDRESS` (set after deploy)
- `ESCROW_BASE_ADDRESS`, `ESCROW_ARB_ADDRESS` (set after deploy)
- `MOLTBOOK_BASE`, `MOLTBOOK_API_KEY` (agent posting/voting)
- `REPO_URL` (submission repo link)


## Agent Memory
The agent stores created bounties, submissions, and awards in `artifacts/agent_state.json`.
If RPC log queries fail, `auto-award` uses this local memory or `--submission-tx` for receipt-based extraction.

## Moltbook Usage (Agent-Only)
Use `read-feed` to discover new posts, `create-post` to submit, and `comment` for votes. Avoid spam and respect rate limits.

## Safety
Use testnet only. Do not use mainnet keys or real funds.
