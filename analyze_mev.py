# ===== analyze_mev.py =====
#
# Usage:
#   python analyze_mev.py
#
# This script:
#   - Loads transactions.csv, blocks.csv, mempool_snapshots.csv, peer_snapshots.csv
#   - Flags DEX swaps based on function selectors
#   - Detects candidate sandwich and backrunning patterns inside blocks
#   - Estimates arrival times from mempool snapshots
#   - Writes:
#       candidate_sandwiches.csv
#       candidate_backruns.csv
#       tx_with_arrival.csv
#       peer_stats.csv
#
# You can adjust paths/config in the CONFIG section.

import pandas as pd
from datetime import datetime

# -----------------------------
# CONFIG
# -----------------------------
TX_CSV = "transactions.csv"
BLOCK_CSV = "blocks.csv"
MEMPOOL_CSV = "mempool_snapshots.csv"
PEER_CSV = "peer_snapshots.csv"

# Uniswap V2 + V3 common swap selectors (4-byte)
# Ref: etherscan / 4byte.directory / docs
DEX_FUNCTION_SELECTORS = {
    # Uniswap V2 Router
    "0x38ed1739": "swapExactTokensForTokens",
    "0x8803dbee": "swapTokensForExactTokens",
    "0x7ff36ab5": "swapExactETHForTokens",
    "0x18cbafe5": "swapExactTokensForETH",
    "0x4a25d94a": "swapTokensForExactETH",
    "0xfb3bdb41": "swapETHForExactTokens",
    # Uniswap V3 Router (exactInputSingle)
    "0x414bf389": "exactInputSingle",
    # You can append more selectors here as needed
}

# Heuristic thresholds
MIN_VICTIM_VALUE_WEI = 0          # you can raise this once you see data
MIN_ATTACKER_VALUE_WEI = 0        # same, for filtering dust
MAX_BLOCK_SCAN_NEIGHBORS = 1      # only immediate neighbors (i-1,i+1)


# -----------------------------
# LOADERS
# -----------------------------

def load_transactions():
    print("[*] Loading transactions.csv ...")
    df = pd.read_csv(TX_CSV)

    # Normalize column names if needed
    # Expecting: blockNumber, blockHash, txIndex, txHash, from, to, valueWei/value, ...
    # In the JS exporter we called it "valueWei" in this script we used "value" there;
    # adapt depending on your actual header.
    if "valueWei" in df.columns:
        df["valueWei"] = df["valueWei"].fillna(0)
    elif "value" in df.columns:
        df["valueWei"] = df["value"].fillna(0)
    else:
        df["valueWei"] = 0

    # Ensure numeric types
    for col in ["blockNumber", "txIndex", "valueWei", "gasUsed", "gas", "gasPriceWei",
                "maxFeePerGasWei", "maxPriorityFeePerGasWei"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Normalize hashes to lowercase for joining
    df["txHash"] = df["txHash"].str.lower()
    df["blockHash"] = df["blockHash"].astype(str).str.lower()

    # Input data normalized
    if "inputData" in df.columns:
        df["inputData"] = df["inputData"].fillna("")
    elif "data" in df.columns:
        df["inputData"] = df["data"].fillna("")
    else:
        df["inputData"] = ""

    return df


def load_blocks():
    print("[*] Loading blocks.csv ...")
    df = pd.read_csv(BLOCK_CSV)

    # Expect: blockNumber, blockHash, timestamp, baseFeePerGas, gasLimit, gasUsed, txCount
    df["blockNumber"] = pd.to_numeric(df["blockNumber"], errors="coerce")
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["blockHash"] = df["blockHash"].astype(str).str.lower()
    return df


def load_mempool():
    print("[*] Loading mempool_snapshots.csv ...")
    df = pd.read_csv(MEMPOOL_CSV)

    # Normalize
    df["snapshotTime"] = pd.to_datetime(df["snapshotTime"], errors="coerce", utc=True)
    df["txHash"] = df["txHash"].astype(str).str.lower()
    for col in ["valueWei", "gas", "gasPriceWei", "maxFeePerGasWei", "maxPriorityFeePerGasWei"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_peers():
    try:
        print("[*] Loading peer_snapshots.csv ...")
        df = pd.read_csv(PEER_CSV)
        df["snapshotTime"] = pd.to_datetime(df["snapshotTime"], errors="coerce", utc=True)
        return df
    except FileNotFoundError:
        print("[!] peer_snapshots.csv not found, skipping peer analysis.")
        return None


# -----------------------------
# FEATURE: DEX Swap Detection
# -----------------------------

def flag_dex_swaps(tx_df):
    print("[*] Flagging DEX swaps based on function selectors ...")

    def selector_from_input(data):
        if isinstance(data, str) and data.startswith("0x") and len(data) >= 10:
            return data[:10].lower()
        return ""

    tx_df["funcSelector"] = tx_df["inputData"].apply(selector_from_input)
    tx_df["dexFunc"] = tx_df["funcSelector"].map(DEX_FUNCTION_SELECTORS).fillna("")
    tx_df["isDexSwap"] = tx_df["dexFunc"] != ""

    print(f"    Detected {tx_df['isDexSwap'].sum()} DEX swap-like transactions.")
    return tx_df


# -----------------------------
# FEATURE: Arrival Time Joining
# -----------------------------

def join_arrival_times(tx_df, mp_df, block_df):
    print("[*] Estimating arrival times from mempool snapshots ...")

    # Earliest seen snapshot per txHash
    first_seen = (
        mp_df
        .groupby("txHash")["snapshotTime"]
        .min()
        .reset_index()
        .rename(columns={"snapshotTime": "firstSeen"})
    )

    tx_df = tx_df.merge(first_seen, on="txHash", how="left")

    # Convert block timestamp to datetime in UTC
    if "blockNumber" in tx_df.columns:
        block_ts = block_df[["blockNumber", "timestamp"]].copy()
        block_ts["blockTime"] = pd.to_datetime(block_ts["timestamp"], unit="s", utc=True)
        tx_df = tx_df.merge(block_ts, on="blockNumber", how="left")

    # Arrival delta (seconds) between firstSeen and blockTime
    tx_df["arrivalDeltaSec"] = (tx_df["blockTime"] - tx_df["firstSeen"]).dt.total_seconds()
    return tx_df


# -----------------------------
# MEV Detection Heuristics
# -----------------------------

def detect_sandwiches(tx_df):
    print("[*] Detecting candidate sandwich attacks ...")

    # Only look at blocks with >2 tx
    tx_df_sorted = tx_df.sort_values(["blockNumber", "txIndex"]).reset_index(drop=True)

    candidates = []

    # We'll walk by block
    for block_num, g in tx_df_sorted.groupby("blockNumber"):
        g = g.sort_values("txIndex").reset_index(drop=True)
        n = len(g)
        if n < 3:
            continue

        for idx in range(1, n - 1):
            victim = g.iloc[idx]
            if not victim.get("isDexSwap", False):
                continue

            # Apply simple victim filter (optional)
            if victim["valueWei"] < MIN_VICTIM_VALUE_WEI:
                continue

            prev_tx = g.iloc[idx - 1]
            next_tx = g.iloc[idx + 1]

            # Same pool/DEX contract for all three
            same_to_prev = (prev_tx["to"] == victim["to"])
            same_to_next = (next_tx["to"] == victim["to"])

            # Attacker same address for prev+next, different from victim
            same_attacker_addr = (prev_tx["from"] == next_tx["from"]) and (prev_tx["from"] != victim["from"])

            # All should be DEX swaps if we detected selectors
            prev_is_swap = bool(prev_tx.get("isDexSwap", False))
            next_is_swap = bool(next_tx.get("isDexSwap", False))

            # Optional: attacker amount filter
            if prev_tx["valueWei"] < MIN_ATTACKER_VALUE_WEI or next_tx["valueWei"] < MIN_ATTACKER_VALUE_WEI:
                continue

            if same_to_prev and same_to_next and same_attacker_addr and prev_is_swap and next_is_swap:
                # candidate sandwich
                candidates.append({
                    "blockNumber": block_num,
                    "victimTxIndex": victim["txIndex"],
                    "victimTxHash": victim["txHash"],
                    "victimFrom": victim["from"],
                    "victimTo": victim["to"],
                    "attacker": prev_tx["from"],
                    "frontTxHash": prev_tx["txHash"],
                    "frontTxIndex": prev_tx["txIndex"],
                    "backTxHash": next_tx["txHash"],
                    "backTxIndex": next_tx["txIndex"],
                    "victimFunc": victim.get("dexFunc", ""),
                    "frontFunc": prev_tx.get("dexFunc", ""),
                    "backFunc": next_tx.get("dexFunc", ""),
                    "victimValueWei": victim["valueWei"],
                    "frontValueWei": prev_tx["valueWei"],
                    "backValueWei": next_tx["valueWei"],
                    "victimArrivalDeltaSec": victim.get("arrivalDeltaSec", None),
                    "frontArrivalDeltaSec": prev_tx.get("arrivalDeltaSec", None),
                    "backArrivalDeltaSec": next_tx.get("arrivalDeltaSec", None),
                })

    cand_df = pd.DataFrame(candidates)
    print(f"    Found {len(cand_df)} candidate sandwich patterns.")
    return cand_df


def detect_backruns(tx_df):
    print("[*] Detecting candidate backrunning patterns ...")

    tx_df_sorted = tx_df.sort_values(["blockNumber", "txIndex"]).reset_index(drop=True)

    candidates = []

    for block_num, g in tx_df_sorted.groupby("blockNumber"):
        g = g.sort_values("txIndex").reset_index(drop=True)
        n = len(g)
        if n < 2:
            continue

        for idx in range(0, n - 1):
            victim = g.iloc[idx]
            next_tx = g.iloc[idx + 1]

            # victim is a DEX swap
            if not victim.get("isDexSwap", False):
                continue

            if victim["valueWei"] < MIN_VICTIM_VALUE_WEI:
                continue

            # attacker is different address and is also DEX swap to the same contract
            different_sender = victim["from"] != next_tx["from"]
            same_to = victim["to"] == next_tx["to"]
            next_is_swap = bool(next_tx.get("isDexSwap", False))

            if different_sender and same_to and next_is_swap:
                candidates.append({
                    "blockNumber": block_num,
                    "victimTxIndex": victim["txIndex"],
                    "victimTxHash": victim["txHash"],
                    "victimFrom": victim["from"],
                    "victimTo": victim["to"],
                    "attacker": next_tx["from"],
                    "backrunTxHash": next_tx["txHash"],
                    "backrunTxIndex": next_tx["txIndex"],
                    "victimFunc": victim.get("dexFunc", ""),
                    "backrunFunc": next_tx.get("dexFunc", ""),
                    "victimValueWei": victim["valueWei"],
                    "backrunValueWei": next_tx["valueWei"],
                    "victimArrivalDeltaSec": victim.get("arrivalDeltaSec", None),
                    "backrunArrivalDeltaSec": next_tx.get("arrivalDeltaSec", None),
                })

    cand_df = pd.DataFrame(candidates)
    print(f"    Found {len(cand_df)} candidate backrun patterns.")
    return cand_df


# -----------------------------
# Peer / Network Stats
# -----------------------------

def summarize_peers(peer_df):
    if peer_df is None or peer_df.empty:
        return None

    print("[*] Summarizing peer stats ...")

    # Count peers over time
    peer_counts = (
        peer_df
        .groupby("snapshotTime")["peerId"]
        .nunique()
        .reset_index()
        .rename(columns={"peerId": "peerCount"})
    )

    # Client diversity (rough; based on 'name' prefix)
    peer_df["client"] = peer_df["name"].fillna("").str.split("/").str[0]
    client_counts = (
        peer_df
        .groupby(["snapshotTime", "client"])["peerId"]
        .nunique()
        .reset_index()
        .rename(columns={"peerId": "clientPeerCount"})
    )

    # Combine as you like; for now just write both to CSV
    peer_counts.to_csv("peer_counts.csv", index=False)
    client_counts.to_csv("peer_client_counts.csv", index=False)

    print("    Wrote peer_counts.csv and peer_client_counts.csv.")
    return peer_counts, client_counts


# -----------------------------
# MAIN
# -----------------------------

def main():
    # Load
    tx_df = load_transactions()
    block_df = load_blocks()
    mp_df = load_mempool()
    peer_df = load_peers()

    # Flag DEX swaps
    tx_df = flag_dex_swaps(tx_df)

    # Join arrival times
    tx_df = join_arrival_times(tx_df, mp_df, block_df)

    # Save enriched tx for later analysis
    tx_df.to_csv("tx_with_arrival.csv", index=False)
    print("[*] Wrote tx_with_arrival.csv (transactions + arrival time).")

    # Detect MEV patterns
    sandwich_df = detect_sandwiches(tx_df)
    backrun_df = detect_backruns(tx_df)

    # Export candidates
    sandwich_df.to_csv("candidate_sandwiches.csv", index=False)
    backrun_df.to_csv("candidate_backruns.csv", index=False)
    print("[*] Wrote candidate_sandwiches.csv and candidate_backruns.csv.")

    # Peer stats
    summarize_peers(peer_df)

    print("[*] Done.")


if __name__ == "__main__":
    main()
