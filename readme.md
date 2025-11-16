# Multi-Layer MEV Measurement Framework (Ethereum Mainnet)

This repository contains a fully reproducible framework for Multi-layer measurement of Maximal Extractable Value (MEV) on Ethereum. The pipeline collects synchronized mempool, block, and network-layer data from a live Ethereum Sepolia node and detects candidate backrunning behavior.

To run this experiment, you must operate a full Ethereum mainnet node using both:

- **Geth (Execution Layer)**
- **Prysm (Consensus Layer)**

The node must expose `eth`, `net`, `web3`, `txpool`, and `admin` APIs over HTTP.

Only a small 5-block dataset is included in this repository due to space constraints. The code supports larger runs (100–4500+ blocks).

---

## Repository Structure
```
.
├── analyze_mev.py
├── export_mev_data.js
├── export_mev_data_live.js
├── export_mempool_snapshot_live.js
├── transactions.csv
├── blocks.csv
├── mempool_snapshots.csv
├── peer_snapshots.csv
├── resultss_all.md
├── package.json
├── package-lock.json
└── README.md
```

---

# 1. Node Requirements

An Ethereum minnet node must run with:

### **Geth (Execution Layer)**
Enable required RPC modules:

```
geth \
  --http \
  --http.addr 0.0.0.0 \
  --http.port 8545 \
  --http.api eth,net,web3,txpool,admin \
  --ws \
  --ws.api eth,net,web3,txpool,admin
```

### **Prysm (Consensus Layer)**

```
prysm-beacon-chain --mainnet --execution-endpoint=http://127.0.0.1:8545
prysm-validator --mainet
```

Your node must be fully synced before running any exports.

---

# 2. Software Requirements

### Python
```
pip install pandas
```

### Node.js
Requires Node ≥ 18 and npm.

Install dependencies:
```
npm install
```

---

# 3. Data Export Instructions

You may run exports in three modes: historical, live, or mempool snapshots.

---

## 3.1 Export Historical Blocks
```
node export_mev_data.js blocks <fromBlock> <toBlock>
```

Example:

```
node export_mev_data.js blocks 4580000 4580100
```

Produces:

- `blocks.csv`
- `transactions.csv`

---

## 3.2 Export Live Latest N Blocks
```
node export_mev_data.js blocksLive 100
```

Produces:

- `blocks_live.csv`
- `transactions_live.csv`

---

## 3.3 Mempool + Peer Snapshots
Take snapshots every `<interval>` seconds until `<maxBlocks>` blocks pass:

```
node export_mev_data.js mempool 5 1000
```

Outputs:

- `mempool_snapshots.csv`
- `peer_snapshots.csv`

---

# 4. Running the Analyzer

After exporting the CSVs, run:

```
python3 analyze_mev.py
```

This script:

- Flags DEX swaps  
- Computes mempool arrival times  
- Detects MEV patterns  
- Summarizes peer connectivity  

Outputs:

- `tx_with_arrival.csv`
- `candidate_backruns.csv`
- `candidate_sandwiches.csv`
- `peer_counts.csv`
- `peer_client_counts.csv`

---

# 5. Sample Dataset (5-Block Example Included)

Example analyzer output:

```
Detected 6 DEX swap-like transactions.
Found 0 candidate sandwich patterns.
Found 0 candidate backrun patterns.
```

For larger experiments, see `resultss_all.md`.

---

# 6. Interpretation of Results

### **Backrunning Detection**
Victim swap → attacker swap immediately after it in the same block.

### **Arrival-Time Delta**
```
arrivalDeltaSec = blockTime - firstSeenTime
```

### **Peer Stats**
Stable peer counts imply consistent network visibility.

---

# 7. Troubleshooting

**"txpool_content RPC failed"**  
Enable:
```
--http.api txpool,admin
```

**"eth_getBlockByNumber failed"**  
Check connectivity:
```
curl -X POST http://127.0.0.1:8545
```

**Empty DEX swap detection**  
Ensure the node is connected to Sepolia.

---

# 8. Purpose

This codebase supports empirical research into:

- Mempool visibility  
- Block-level ordering  
- Network-layer propagation  
- Backrunning MEV behavior  
- Cross-layer transaction dynamics  

---

# 9. License
MIT License

---

# 10. Acknowledgment
Repository prepared without personal identifiers to comply with double-blind review policies.
