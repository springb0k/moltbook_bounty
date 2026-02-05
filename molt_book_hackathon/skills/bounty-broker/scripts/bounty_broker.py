#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import requests
from web3 import Web3
from web3.middleware import geth_poa_middleware

try:
    from solcx import compile_standard, install_solc, set_solc_version
except Exception:
    compile_standard = None
    install_solc = None
    set_solc_version = None

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = ROOT / "contracts"
ARTIFACTS_DIR = ROOT / "artifacts"
STATE_PATH = ARTIFACTS_DIR / "agent_state.json"
ENV_PATH = ROOT / ".env"
SOLC_VERSION = "0.8.20"
USDC_DECIMALS = 6
MOLTBOOK_BASE_DEFAULT = "https://www.moltbook.com/api/v1"

load_dotenv(ENV_PATH)

@dataclass
class ChainConfig:
    name: str
    chain_id: int
    rpc_env: str
    usdc_env: str
    escrow_env: str
    explorer_tx: str

CHAINS = {
    "sepolia": ChainConfig(
        name="sepolia",
        chain_id=11155111,
        rpc_env="SEPOLIA_RPC",
        usdc_env="USDC_SEPOLIA_ADDRESS",
        escrow_env="ESCROW_SEPOLIA_ADDRESS",
        explorer_tx="https://sepolia.etherscan.io/tx/",
    ),
    "base": ChainConfig(
        name="base",
        chain_id=84532,
        rpc_env="BASE_SEPOLIA_RPC",
        usdc_env="USDC_BASE_ADDRESS",
        escrow_env="ESCROW_BASE_ADDRESS",
        explorer_tx="https://sepolia.basescan.org/tx/",
    ),
    "arb": ChainConfig(
        name="arb",
        chain_id=421614,
        rpc_env="ARB_SEPOLIA_RPC",
        usdc_env="USDC_ARB_ADDRESS",
        escrow_env="ESCROW_ARB_ADDRESS",
        explorer_tx="https://sepolia.arbiscan.io/tx/",
    ),
}

USDC_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "transfer",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "transferFrom",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [],
    },
]


def get_env(key: str, required: bool = False) -> str:
    val = os.getenv(key, "").strip()
    if required and not val:
        raise SystemExit(f"Missing env var: {key}")
    return val


def load_state() -> Dict[str, Any]:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return {"bounties": {}, "submissions": {}, "awards": {}}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"bounties": {}, "submissions": {}, "awards": {}}


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def state_key(chain: ChainConfig, bounty_id: int) -> str:
    return f"{chain.name}:{bounty_id}"


def record_bounty(state: Dict[str, Any], chain: ChainConfig, bounty_id: int, creator: str, arbiter: str, metadata_uri: str, amount: int, deadline: int, tx_hash: str, block_number: int) -> None:
    key = state_key(chain, bounty_id)
    state.setdefault("bounties", {})[key] = {
        "bountyId": bounty_id,
        "chain": chain.name,
        "creator": creator,
        "arbiter": arbiter,
        "metadataURI": metadata_uri,
        "amount": amount,
        "deadline": deadline,
        "txHash": tx_hash,
        "blockNumber": block_number,
        "timestamp": int(time.time()),
    }


def record_submission(state: Dict[str, Any], chain: ChainConfig, bounty_id: int, solver: str, solution_uri: str, tx_hash: str, block_number: int) -> None:
    key = state_key(chain, bounty_id)
    subs = state.setdefault("submissions", {}).setdefault(key, [])
    if any(s.get("txHash") == tx_hash for s in subs):
        return
    subs.append({
        "bountyId": bounty_id,
        "chain": chain.name,
        "solver": solver,
        "solutionURI": solution_uri,
        "txHash": tx_hash,
        "blockNumber": block_number,
        "timestamp": int(time.time()),
    })


def record_award(state: Dict[str, Any], chain: ChainConfig, bounty_id: int, solver: str, tx_hash: str, block_number: int) -> None:
    key = state_key(chain, bounty_id)
    state.setdefault("awards", {})[key] = {
        "bountyId": bounty_id,
        "chain": chain.name,
        "solver": solver,
        "txHash": tx_hash,
        "blockNumber": block_number,
        "timestamp": int(time.time()),
    }


def decode_submission_receipt(w3: Web3, escrow, tx_hash: str) -> Dict[str, Any]:
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    events = escrow.events.Submission().process_receipt(receipt)
    if not events:
        raise SystemExit("No Submission event found in tx")
    ev = events[0]["args"]
    return {
        "bountyId": int(ev["bountyId"]),
        "solver": ev["solver"],
        "solutionURI": ev.get("solutionURI", ""),
        "blockNumber": receipt.blockNumber,
    }


def get_moltbook_base() -> str:
    return get_env("MOLTBOOK_BASE") or MOLTBOOK_BASE_DEFAULT


def moltbook_request(path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    api_key = get_env("MOLTBOOK_API_KEY", required=True)
    base = get_moltbook_base().rstrip("/")
    url = f"{base}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, json=body, timeout=30)
    if not resp.ok:
        raise SystemExit(f"Moltbook error: {resp.status_code} {resp.text}")
    return resp.json()


def create_post(title: str, content: str, submolt: str = "general") -> Dict[str, Any]:
    return moltbook_request("/posts", "POST", {
        "title": title,
        "content": content,
        "submolt": submolt,
    })


def comment_on_post(post_id: str, content: str) -> Dict[str, Any]:
    return moltbook_request(f"/posts/{post_id}/comments", "POST", {
        "content": content,
    })


def read_feed(limit: int = 10) -> Dict[str, Any]:
    return moltbook_request(f"/feed?sort=new&limit={limit}")


def get_latest_bounty(state: Dict[str, Any], chain_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    bounties = state.get("bounties", {})
    items = [b for b in bounties.values() if chain_name is None or b.get("chain") == chain_name]
    if not items:
        return None
    items.sort(key=lambda b: (b.get("timestamp", 0), b.get("bountyId", 0)))
    return items[-1]


def get_submission_for_bounty(state: Dict[str, Any], chain: ChainConfig, bounty_id: int) -> Optional[Dict[str, Any]]:
    key = state_key(chain, bounty_id)
    subs = state.get("submissions", {}).get(key, [])
    if not subs:
        return None
    subs.sort(key=lambda s: (s.get("blockNumber", 0), s.get("timestamp", 0)))
    return subs[0]


def get_award_for_bounty(state: Dict[str, Any], chain: ChainConfig, bounty_id: int) -> Optional[Dict[str, Any]]:
    key = state_key(chain, bounty_id)
    return state.get("awards", {}).get(key)


def build_submission_text(title: str, repo_url: str, chain: ChainConfig, bounty: Dict[str, Any], submission: Optional[Dict[str, Any]], award: Optional[Dict[str, Any]]) -> str:
    lines = []
    lines.append("#USDCHackathon ProjectSubmission Skill")
    lines.append("")
    lines.append(f"Title: {title}")
    lines.append("")
    lines.append("Summary:")
    lines.append("A real OpenClaw skill that lets agents create, discover, submit, and settle USDC bounties on testnet via on-chain escrow. No UI, no humans in the loop. Agents escrow USDC, submit solutions, and award or refund based on on-chain events.")
    lines.append("")
    lines.append("Repo:")
    lines.append(repo_url)
    lines.append("")
    lines.append("Deployed contracts:")
    lines.append(f"{chain.name.capitalize()} USDC: {get_env(chain.usdc_env) or '<set usdc>'}")
    lines.append(f"{chain.name.capitalize()} Escrow: {get_env(chain.escrow_env) or '<set escrow>'}")
    if get_env("ESCROW_BASE_ADDRESS"):
        lines.append(f"Base Sepolia Escrow: {get_env('ESCROW_BASE_ADDRESS')}")
    if get_env("ESCROW_ARB_ADDRESS"):
        lines.append(f"Arbitrum Sepolia Escrow: {get_env('ESCROW_ARB_ADDRESS')}")
    lines.append("")
    lines.append("Example txs:")
    create_tx = bounty.get("txHash") if bounty else None
    if create_tx:
        lines.append(f"- Create bounty: {chain.explorer_tx}{create_tx}")
    else:
        lines.append("- Create bounty: <tx hash>")
    if submission and submission.get("txHash"):
        lines.append(f"- Submit solution: {chain.explorer_tx}{submission['txHash']}")
    else:
        lines.append("- Submit solution: <tx hash>")
    if award and award.get("txHash"):
        lines.append(f"- Award bounty: {chain.explorer_tx}{award['txHash']}")
    else:
        lines.append("- Award bounty: <tx hash>")
    lines.append("")
    lines.append("How agents use it:")
    lines.append("- Create bounty: python skills/bounty-broker/scripts/bounty_broker.py create --amount 5 --deadline-seconds 3600 --metadata-uri <uri>")
    lines.append("- Submit: python skills/bounty-broker/scripts/bounty_broker.py submit --bounty-id 1 --solution-uri <uri>")
    lines.append("- Auto-award: python skills/bounty-broker/scripts/bounty_broker.py auto-award --bounty-id 1")

    return "
".join(lines)


def parse_amount_usdc(amount: str) -> int:
    d = Decimal(amount)
    q = d.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    if q <= 0:
        raise SystemExit("amount must be > 0")
    return int(q * Decimal(10 ** USDC_DECIMALS))


def format_amount_usdc(amount_6: int) -> str:
    return f"{Decimal(amount_6) / Decimal(10 ** USDC_DECIMALS):.6f}"


def to_checksum(w3: Web3, addr: str) -> str:
    return w3.to_checksum_address(addr)


def get_chain(name: Optional[str]) -> ChainConfig:
    if not name:
        name = get_env("DEFAULT_CHAIN") or "base"
    name = name.lower()
    if name not in CHAINS:
        raise SystemExit(f"Unknown chain: {name}")
    return CHAINS[name]


def get_w3(chain: ChainConfig) -> Web3:
    rpc = get_env(chain.rpc_env, required=True)
    w3 = Web3(Web3.HTTPProvider(rpc))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3


def get_account(w3: Web3):
    pk = get_env("AGENT_PRIVATE_KEY", required=True)
    return w3.eth.account.from_key(pk)


def ensure_solc():
    if compile_standard is None:
        raise SystemExit("py-solc-x not installed. Run: pip install -r requirements.txt")
    try:
        set_solc_version(SOLC_VERSION)
    except Exception:
        if install_solc is None:
            raise SystemExit("solc not available and auto-install disabled")
        install_solc(SOLC_VERSION)
        set_solc_version(SOLC_VERSION)


def compile_contracts() -> Dict[str, Dict[str, Any]]:
    ensure_solc()
    sources = {}
    for name in ["MockUSDC.sol", "BountyEscrow.sol"]:
        path = CONTRACTS_DIR / name
        sources[name] = {"content": path.read_text()}

    input_json = {
        "language": "Solidity",
        "sources": sources,
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode"]}},
        },
    }

    compiled = compile_standard(input_json)
    results = {}
    for file_name, contracts in compiled["contracts"].items():
        for contract_name, data in contracts.items():
            results[contract_name] = {
                "abi": data["abi"],
                "bytecode": f"0x{data['evm']['bytecode']['object']}",
            }
    return results


def load_artifact(name: str) -> Dict[str, Any]:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())

    compiled = compile_contracts()
    if name not in compiled:
        raise SystemExit(f"Contract not found: {name}")
    path.write_text(json.dumps(compiled[name], indent=2))
    return compiled[name]


def build_tx(w3: Web3, account, tx: Dict[str, Any]) -> Dict[str, Any]:
    tx.setdefault("nonce", w3.eth.get_transaction_count(account.address))
    tx.setdefault("chainId", w3.eth.chain_id)
    if "gas" not in tx:
        tx["gas"] = w3.eth.estimate_gas(tx)

    latest = w3.eth.get_block("latest")
    is_1559 = "baseFeePerGas" in latest or tx.get("type") == 2

    if is_1559:
        if "maxPriorityFeePerGas" not in tx:
            try:
                tx["maxPriorityFeePerGas"] = w3.eth.max_priority_fee
            except Exception:
                tx["maxPriorityFeePerGas"] = w3.to_wei(1.5, "gwei")
        if "maxFeePerGas" not in tx:
            base_fee = latest.get("baseFeePerGas", 0)
            tx["maxFeePerGas"] = base_fee * 2 + tx["maxPriorityFeePerGas"]
        tx.pop("gasPrice", None)
        tx["type"] = 2
    else:
        if "gasPrice" not in tx:
            tx["gasPrice"] = w3.eth.gas_price

    return tx


def send_tx(w3: Web3, account, tx: Dict[str, Any]) -> Dict[str, Any]:
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return {"tx_hash": tx_hash.hex(), "receipt": receipt}


def deploy_contract(w3: Web3, account, name: str, args: List[Any]):
    artifact = load_artifact(name)
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    tx = contract.constructor(*args).build_transaction({"from": account.address})
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)
    addr = result["receipt"].contractAddress
    return addr, result["tx_hash"]


def get_contract(w3: Web3, address: str, name: str):
    artifact = load_artifact(name)
    return w3.eth.contract(address=to_checksum(w3, address), abi=artifact["abi"])


def ensure_allowance(w3: Web3, account, usdc_addr: str, spender: str, amount: int):
    usdc = w3.eth.contract(address=to_checksum(w3, usdc_addr), abi=USDC_ABI)
    allowance = usdc.functions.allowance(account.address, spender).call()
    if allowance >= amount:
        return None
    tx = usdc.functions.approve(spender, 2 ** 256 - 1).build_transaction({"from": account.address})
    tx = build_tx(w3, account, tx)
    return send_tx(w3, account, tx)


def cmd_deploy(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)

    usdc_addr = get_env(chain.usdc_env)
    if not usdc_addr or args.deploy_mock:
        usdc_addr, usdc_tx = deploy_contract(w3, account, "MockUSDC", [])
        print(f"Deployed MockUSDC: {usdc_addr} ({chain.explorer_tx}{usdc_tx})")

        usdc = w3.eth.contract(address=to_checksum(w3, usdc_addr), abi=USDC_ABI)
        mint_amount = 10_000 * 10 ** USDC_DECIMALS
        tx = usdc.functions.mint(account.address, mint_amount).build_transaction({"from": account.address})
        tx = build_tx(w3, account, tx)
        mint_result = send_tx(w3, account, tx)
        print(f"Minted 10000 USDC to agent: {chain.explorer_tx}{mint_result['tx_hash']}")

    escrow_addr, escrow_tx = deploy_contract(w3, account, "BountyEscrow", [to_checksum(w3, usdc_addr)])
    print(f"Deployed BountyEscrow: {escrow_addr} ({chain.explorer_tx}{escrow_tx})")

    print("\nAdd these to .env:")
    print(f"{chain.usdc_env}={usdc_addr}")
    print(f"{chain.escrow_env}={escrow_addr}")


def cmd_create(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)

    usdc_addr = get_env(chain.usdc_env, required=True)
    escrow_addr = get_env(chain.escrow_env, required=True)

    amount = parse_amount_usdc(args.amount)
    deadline = args.deadline
    if not deadline:
        deadline = int(time.time()) + int(args.deadline_seconds)

    ensure_allowance(w3, account, usdc_addr, escrow_addr, amount)

    escrow = get_contract(w3, escrow_addr, "BountyEscrow")
    arbiter = args.arbiter or account.address
    tx = escrow.functions.createBounty(amount, deadline, arbiter, args.metadata_uri).build_transaction(
        {"from": account.address}
    )
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)
    receipt = result["receipt"]

    events = escrow.events.BountyCreated().process_receipt(receipt)
    bounty_id = events[0]["args"]["bountyId"] if events else None

    if bounty_id is not None:
        state = load_state()
        record_bounty(
            state,
            chain,
            int(bounty_id),
            account.address,
            arbiter,
            args.metadata_uri,
            amount,
            deadline,
            result["tx_hash"],
            receipt.blockNumber,
        )
        save_state(state)

    print(f"Created bounty {bounty_id} ({chain.explorer_tx}{result['tx_hash']})")


def cmd_list(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    from_block = int(args.from_block)
    if from_block <= 0:
        latest_block = w3.eth.block_number
        from_block = max(latest_block - 5000, 0)
        print(f"Using from-block {from_block} (latest {latest_block})")
    logs = escrow.events.BountyCreated().get_logs(fromBlock=from_block, toBlock="latest")

    now_ts = w3.eth.get_block("latest")["timestamp"]
    print("bountyId status amount deadline submissions arbiter creator")
    for log in logs:
        bounty_id = log["args"]["bountyId"]
        bounty = escrow.functions.getBounty(bounty_id).call()
        status = "open"
        if bounty[4]:
            status = "awarded"
        elif bounty[5]:
            status = "canceled"
        elif now_ts > bounty[3]:
            status = "expired"

        amount = format_amount_usdc(bounty[2])
        print(
            f"{bounty_id} {status} {amount} {bounty[3]} {bounty[7]} {bounty[1]} {bounty[0]}"
        )


def cmd_submit(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    tx = escrow.functions.submitSolution(int(args.bounty_id), args.solution_uri).build_transaction(
        {"from": account.address}
    )
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)
    state = load_state()
    record_submission(
        state,
        chain,
        int(args.bounty_id),
        account.address,
        args.solution_uri,
        result["tx_hash"],
        result["receipt"].blockNumber,
    )
    save_state(state)
    print(f"Submitted solution ({chain.explorer_tx}{result['tx_hash']})")


def cmd_award(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    tx = escrow.functions.awardBounty(int(args.bounty_id), args.solver).build_transaction(
        {"from": account.address}
    )
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)
    state = load_state()
    record_award(
        state,
        chain,
        int(args.bounty_id),
        args.solver,
        result["tx_hash"],
        result["receipt"].blockNumber,
    )
    save_state(state)
    print(f"Awarded bounty ({chain.explorer_tx}{result['tx_hash']})")


def cmd_auto_award(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    bounty_id = int(args.bounty_id)
    solver = None

    if args.submission_tx:
        submission = decode_submission_receipt(w3, escrow, args.submission_tx)
        if submission["bountyId"] != bounty_id:
            raise SystemExit("Submission tx bountyId mismatch")
        solver = submission["solver"]
        state = load_state()
        record_submission(
            state,
            chain,
            bounty_id,
            submission["solver"],
            submission.get("solutionURI", ""),
            args.submission_tx,
            submission["blockNumber"],
        )
        save_state(state)
    elif args.solver:
        solver = args.solver
    else:
        state = load_state()
        key = state_key(chain, bounty_id)
        subs = state.get("submissions", {}).get(key, [])
        if subs:
            subs_sorted = sorted(subs, key=lambda s: (s.get("blockNumber", 0), s.get("timestamp", 0)))
            solver = subs_sorted[0]["solver"]
            print(f"Selected earliest local submission: {solver}")
        else:
            from_block = int(args.from_block)
            latest_block = w3.eth.block_number
            if from_block <= 0:
                from_block = max(latest_block - 500, 0)
                print(f"Using from-block {from_block} (latest {latest_block})")

            logs = []
            step = 500
            current = from_block
            while current <= latest_block:
                to_block = min(current + step - 1, latest_block)
                try:
                    chunk = escrow.events.Submission().get_logs(
                        fromBlock=current,
                        toBlock=to_block,
                        argument_filters={"bountyId": bounty_id},
                    )
                    if chunk:
                        logs.extend(chunk)
                except Exception as e:
                    msg = str(e)
                    if "400" in msg and step > 50:
                        step = max(50, step // 2)
                        continue
                    raise
                current = to_block + 1

            if not logs:
                raise SystemExit("No submissions found. Use submit with this CLI or pass --submission-tx/--solver.")

            logs_sorted = sorted(logs, key=lambda l: (l["blockNumber"], l["logIndex"]))
            solver = logs_sorted[0]["args"]["solver"]

    print(f"Auto-awarding to {solver}")

    tx = escrow.functions.awardBounty(bounty_id, solver).build_transaction({"from": account.address})
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)

    state = load_state()
    record_award(
        state,
        chain,
        bounty_id,
        solver,
        result["tx_hash"],
        result["receipt"].blockNumber,
    )
    save_state(state)
    print(f"Awarded bounty ({chain.explorer_tx}{result['tx_hash']})")


def cmd_record_submission(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    submission = decode_submission_receipt(w3, escrow, args.tx)
    state = load_state()
    record_submission(
        state,
        chain,
        int(submission["bountyId"]),
        submission["solver"],
        submission.get("solutionURI", ""),
        args.tx,
        submission["blockNumber"],
    )
    save_state(state)
    print(f"Recorded submission for bounty {submission['bountyId']} solver {submission['solver']}")


def cmd_refund(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    tx = escrow.functions.refundBounty(int(args.bounty_id)).build_transaction({"from": account.address})
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)
    print(f"Refunded bounty ({chain.explorer_tx}{result['tx_hash']})")


def cmd_cancel(args):
    chain = get_chain(args.chain)
    w3 = get_w3(chain)
    account = get_account(w3)
    escrow_addr = get_env(chain.escrow_env, required=True)
    escrow = get_contract(w3, escrow_addr, "BountyEscrow")

    tx = escrow.functions.cancelBounty(int(args.bounty_id)).build_transaction({"from": account.address})
    tx = build_tx(w3, account, tx)
    result = send_tx(w3, account, tx)
    print(f"Canceled bounty ({chain.explorer_tx}{result['tx_hash']})")


def cmd_submission_template(_args):
    base_escrow = get_env("ESCROW_BASE_ADDRESS")
    arb_escrow = get_env("ESCROW_ARB_ADDRESS")

    print("#USDCHackathon ProjectSubmission Skill")
    print("\nTitle: Bounty Broker - Agent-native USDC escrow for task coordination")
    print("\nSummary:")
    print("A real OpenClaw skill that lets agents create, discover, submit, and settle USDC bounties on testnet via an on-chain escrow. No UI, no humans in the loop. Agents escrow USDC, submit solutions, and award or refund based on on-chain events.")
    print("\nRepo:")
    print("<add your GitHub or gitpad link>")
    print("\nDeployed contracts:")
    print(f"Base Sepolia Escrow: {base_escrow or '<set ESCROW_BASE_ADDRESS>'}")
    print(f"Arbitrum Sepolia Escrow: {arb_escrow or '<set ESCROW_ARB_ADDRESS>'}")
    print("\nExample txs:")
    print("- Create bounty: <tx hash>")
    print("- Submit solution: <tx hash>")
    print("- Award bounty: <tx hash>")
    print("\nHow agents use it:")
    print("- Create bounty: python skills/bounty-broker/scripts/bounty_broker.py create --amount 5 --deadline-seconds 3600 --metadata-uri <uri>")
    print("- Submit: python skills/bounty-broker/scripts/bounty_broker.py submit --bounty-id 1 --solution-uri <uri>")
    print("- Auto-award: python skills/bounty-broker/scripts/bounty_broker.py auto-award --bounty-id 1")


def cmd_create_post(args):
    result = create_post(args.title, args.content, args.submolt)
    print(json.dumps(result, indent=2))


def cmd_comment(args):
    result = comment_on_post(args.post_id, args.content)
    print(json.dumps(result, indent=2))


def cmd_read_feed(args):
    result = read_feed(args.limit)
    print(json.dumps(result, indent=2))


def cmd_agent_submit(args):
    chain = get_chain(args.chain)
    state = load_state()

    bounty = None
    if args.bounty_id is not None:
        key = state_key(chain, int(args.bounty_id))
        bounty = state.get("bounties", {}).get(key)
    else:
        bounty = get_latest_bounty(state, chain.name)

    if not bounty:
        raise SystemExit("No bounty found in agent memory. Create a bounty or specify --bounty-id.")

    submission = get_submission_for_bounty(state, chain, int(bounty["bountyId"]))
    award = get_award_for_bounty(state, chain, int(bounty["bountyId"]))

    repo_url = args.repo or get_env("REPO_URL")
    if not repo_url:
        raise SystemExit("Missing repo URL. Provide --repo or set REPO_URL in .env")

    title = args.title or "Bounty Broker - Agent-native USDC escrow"
    content = build_submission_text(title, repo_url, chain, bounty, submission, award)

    if args.dry_run:
        print(content)
        return

    result = create_post(title, content, args.submolt)
    print(json.dumps(result, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Bounty Broker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("deploy")
    p.add_argument("--chain", default=None)
    p.add_argument("--deploy-mock", action="store_true", help="Force deploy MockUSDC")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("create")
    p.add_argument("--chain", default=None)
    p.add_argument("--amount", required=True)
    p.add_argument("--metadata-uri", required=True)
    p.add_argument("--arbiter", default=None)
    p.add_argument("--deadline", type=int, default=None)
    p.add_argument("--deadline-seconds", type=int, default=3600)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list")
    p.add_argument("--chain", default=None)
    p.add_argument("--from-block", default=0)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("submit")
    p.add_argument("--chain", default=None)
    p.add_argument("--bounty-id", required=True)
    p.add_argument("--solution-uri", required=True)
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("award")
    p.add_argument("--chain", default=None)
    p.add_argument("--bounty-id", required=True)
    p.add_argument("--solver", required=True)
    p.set_defaults(func=cmd_award)

    p = sub.add_parser("auto-award")
    p.add_argument("--chain", default=None)
    p.add_argument("--bounty-id", required=True)
    p.add_argument("--from-block", default=0)
    p.add_argument("--solver", default=None, help="Directly award to this solver")
    p.add_argument("--submission-tx", default=None, help="Use this submission tx to extract solver")
    p.set_defaults(func=cmd_auto_award)

    p = sub.add_parser("record-submission")
    p.add_argument("--chain", default=None)
    p.add_argument("--tx", required=True)
    p.set_defaults(func=cmd_record_submission)

    p = sub.add_parser("refund")
    p.add_argument("--chain", default=None)
    p.add_argument("--bounty-id", required=True)
    p.set_defaults(func=cmd_refund)

    p = sub.add_parser("cancel")
    p.add_argument("--chain", default=None)
    p.add_argument("--bounty-id", required=True)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("submission-template")
    p.set_defaults(func=cmd_submission_template)

    p = sub.add_parser("create-post")
    p.add_argument("--title", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--submolt", default="general")
    p.set_defaults(func=cmd_create_post)

    p = sub.add_parser("comment")
    p.add_argument("--post-id", required=True)
    p.add_argument("--content", required=True)
    p.set_defaults(func=cmd_comment)

    p = sub.add_parser("read-feed")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_read_feed)

    p = sub.add_parser("agent-submit")
    p.add_argument("--chain", default=None)
    p.add_argument("--bounty-id", type=int, default=None)
    p.add_argument("--repo", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--submolt", default="usdc")
    p.add_argument("--dry-run", action="store_true", help="Print content only, do not post")
    p.set_defaults(func=cmd_agent_submit)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
