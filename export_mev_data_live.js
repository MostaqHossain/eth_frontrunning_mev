// ===== export_mev_data.js =====
// Usage:
//   Historical range:
//     node export_mev_data.js blocks <fromBlock> <toBlock>
//
//   Live latest N blocks (starting from "now"):
//     node export_mev_data.js blocksLive <count>
//
//   Live mempool snapshots:
//     node export_mev_data.js mempool <intervalSeconds>
//
// Make sure your geth node exposes eth, net, web3, txpool, admin over HTTP.

const RPC_URL = process.env.RPC_URL || "http://127.0.0.1:8545";

import { JsonRpcProvider } from "ethers";
import fs from "fs";

const provider = new JsonRpcProvider(RPC_URL);

// --------- helpers ---------

function esc(x) {
  if (x === null || x === undefined) return "";
  const s = String(x);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function hexToDec(hex) {
  if (!hex) return "";
  try {
    return BigInt(hex).toString();
  } catch {
    return "";
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --------- core block export for a single block ---------

async function exportSingleBlock(blockNumber, txFile, blockFile) {
  console.error(`[*] Processing block ${blockNumber}...`);

  const tag = "0x" + blockNumber.toString(16);
  let block;
  try {
    // raw RPC - include full tx objects
    block = await provider.send("eth_getBlockByNumber", [tag, true]);
  } catch (e) {
    console.error(`  [!] Failed to fetch block ${blockNumber}:`, e);
    return;
  }

  if (!block) {
    console.error(`  [!] Block ${blockNumber} not found`);
    return;
  }

  const timestamp = parseInt(block.timestamp, 16);
  const gasLimit = hexToDec(block.gasLimit);
  const gasUsed = hexToDec(block.gasUsed);
  const baseFee = block.baseFeePerGas ? hexToDec(block.baseFeePerGas) : "";
  const txs = block.transactions || [];

  // ---- Block row ----
  blockFile.write(
    [
      esc(blockNumber),
      esc(block.hash.toLowerCase()),
      esc(block.parentHash.toLowerCase()),
      esc(timestamp),
      esc(baseFee),
      esc(gasLimit),
      esc(gasUsed),
      esc(txs.length),
    ].join(",") + "\n",
  );

  // ---- Transactions ----
  for (let i = 0; i < txs.length; i++) {
    const tx = txs[i];

    const txIndex = tx.transactionIndex ? parseInt(tx.transactionIndex, 16) : i;
    const valueWei = tx.value ? hexToDec(tx.value) : "";
    const nonce = tx.nonce ? parseInt(tx.nonce, 16) : "";
    const gas = tx.gas ? hexToDec(tx.gas) : "";
    const gasPrice = tx.gasPrice ? hexToDec(tx.gasPrice) : "";
    const maxFeePerGas = tx.maxFeePerGas ? hexToDec(tx.maxFeePerGas) : "";
    const maxPriorityFeePerGas = tx.maxPriorityFeePerGas ? hexToDec(tx.maxPriorityFeePerGas) : "";
    const inputData = tx.input || "";

    // Get receipt via ethers
    let receipt;
    try {
      receipt = await provider.getTransactionReceipt(tx.hash);
    } catch (e) {
      console.error(`  [!] Failed to get receipt for tx ${tx.hash}:`, e);
      receipt = null;
    }

    const receiptStatus = receipt && typeof receipt.status !== "undefined" ? receipt.status : "";
    const gasUsedTx = receipt && receipt.gasUsed ? receipt.gasUsed.toString() : "";
    const effGasPrice =
      receipt && receipt.effectiveGasPrice ? receipt.effectiveGasPrice.toString() : "";
    const logsCount = receipt && receipt.logs ? receipt.logs.length : 0;
    const firstLogAddress =
      receipt && receipt.logs && receipt.logs.length > 0 ? receipt.logs[0].address : "";

    txFile.write(
      [
        esc(blockNumber),
        esc(block.hash.toLowerCase()),
        esc(txIndex),
        esc(tx.hash.toLowerCase()),
        esc(tx.from ? tx.from.toLowerCase() : ""),
        esc(tx.to ? tx.to.toLowerCase() : ""),
        esc(valueWei),
        esc(nonce),
        esc(gas),
        esc(gasPrice),
        esc(maxFeePerGas),
        esc(maxPriorityFeePerGas),
        esc(tx.type || ""),
        esc(inputData),
        esc(receiptStatus),
        esc(gasUsedTx),
        esc(effGasPrice),
        esc(logsCount),
        esc(firstLogAddress),
      ].join(",") + "\n",
    );
  }
}

// -----------------------------
// MODE 1: Historical range: blocks <fromBlock> <toBlock>
// -----------------------------
async function exportBlocks(fromBlock, toBlock) {
  const txFile = fs.createWriteStream("transactions.csv", { flags: "w" });
  const blockFile = fs.createWriteStream("blocks.csv", { flags: "w" });

  // Block CSV header
  blockFile.write(
    [
      "blockNumber",
      "blockHash",
      "parentHash",
      "timestamp",
      "baseFeePerGas",
      "gasLimit",
      "gasUsed",
      "txCount",
    ].join(",") + "\n",
  );

  // Tx CSV header
  txFile.write(
    [
      "blockNumber",
      "blockHash",
      "txIndex",
      "txHash",
      "from",
      "to",
      "valueWei",
      "nonce",
      "gas",
      "gasPriceWei",
      "maxFeePerGasWei",
      "maxPriorityFeePerGasWei",
      "type",
      "inputData",
      "receiptStatus",
      "gasUsed",
      "effectiveGasPriceWei",
      "logsCount",
      "firstLogAddress",
    ].join(",") + "\n",
  );

  for (let b = fromBlock; b <= toBlock; b++) {
    await exportSingleBlock(b, txFile, blockFile);
  }

  blockFile.end();
  txFile.end();
  console.error("[*] Done. Wrote blocks.csv and transactions.csv");
}

// -----------------------------
// MODE 1b: Live latest N blocks: blocksLive <count>
// -----------------------------
async function exportBlocksLive(count) {
  const txFile = fs.createWriteStream("transactions_live.csv", { flags: "w" });
  const blockFile = fs.createWriteStream("blocks_live.csv", { flags: "w" });

  // headers same as historical
  blockFile.write(
    [
      "blockNumber",
      "blockHash",
      "parentHash",
      "timestamp",
      "baseFeePerGas",
      "gasLimit",
      "gasUsed",
      "txCount",
    ].join(",") + "\n",
  );

  txFile.write(
    [
      "blockNumber",
      "blockHash",
      "txIndex",
      "txHash",
      "from",
      "to",
      "valueWei",
      "nonce",
      "gas",
      "gasPriceWei",
      "maxFeePerGasWei",
      "maxPriorityFeePerGasWei",
      "type",
      "inputData",
      "receiptStatus",
      "gasUsed",
      "effectiveGasPriceWei",
      "logsCount",
      "firstLogAddress",
    ].join(",") + "\n",
  );

  let collected = 0;
  let lastExported = await provider.getBlockNumber();
  console.error(`[*] Starting live export from next block after ${lastExported}`);

  while (collected < count) {
    const latest = await provider.getBlockNumber();

    if (latest <= lastExported) {
      // no new block yet
      await sleep(5000); // 5s
      continue;
    }

    // export all new blocks up to 'latest'
    for (let b = lastExported + 1; b <= latest && collected < count; b++) {
      await exportSingleBlock(b, txFile, blockFile);
      collected++;
      lastExported = b;
      console.error(`[*] Live export progress: ${collected}/${count} blocks`);
    }
  }

  blockFile.end();
  txFile.end();
  console.error(
    `[*] Done. Exported ${collected} live blocks to blocks_live.csv and transactions_live.csv`,
  );
}

// -------------------------------------------
// MODE 2: Live Mempool + Network Snapshots
// -------------------------------------------
async function snapshotMempoolAndNetwork(intervalSec) {
  const mpFile = fs.createWriteStream("mempool_snapshots.csv", { flags: "w" });
  const peerFile = fs.createWriteStream("peer_snapshots.csv", { flags: "w" });

  // Headers
  mpFile.write(
    [
      "snapshotTime",
      "poolType",
      "txHash",
      "from",
      "to",
      "nonce",
      "valueWei",
      "gas",
      "gasPriceWei",
      "maxFeePerGasWei",
      "maxPriorityFeePerGasWei",
      "inputData",
    ].join(",") + "\n",
  );

  peerFile.write(
    ["snapshotTime", "peerId", "name", "remoteAddress", "localAddress"].join(",") + "\n",
  );

  console.error(
    `[*] Taking mempool+peer snapshots every ${intervalSec}s. Press Ctrl+C to stop.`,
  );

  async function oneSnapshot() {
    const snapshotTime = new Date().toISOString();
    console.error(`[*] Snapshot at ${snapshotTime}`);

    // ---- Mempool: txpool_content ----
    let pool;
    try {
      pool = await provider.send("txpool_content", []);
    } catch (e) {
      console.error("[!] txpool_content RPC failed. Is txpool API enabled?", e);
      pool = null;
    }

    if (pool) {
      const { pending = {}, queued = {} } = pool;

      function dumpPool(poolObj, poolType) {
        for (const fromAddr of Object.keys(poolObj)) {
          const nonceMap = poolObj[fromAddr];
          for (const nonceStr of Object.keys(nonceMap)) {
            const tx = nonceMap[nonceStr];
            const gasPrice = tx.gasPrice || "";
            const maxFeePerGas = tx.maxFeePerGas || "";
            const maxPriorityFeePerGas = tx.maxPriorityFeePerGas || "";

            mpFile.write(
              [
                esc(snapshotTime),
                esc(poolType),
                esc(tx.hash || ""),
                esc(tx.from || fromAddr),
                esc(tx.to || ""),
                esc(tx.nonce || nonceStr),
                esc(tx.value || ""),
                esc(tx.gas || ""),
                esc(gasPrice),
                esc(maxFeePerGas),
                esc(maxPriorityFeePerGas),
                esc(tx.input || tx.data || ""),
              ].join(",") + "\n",
            );
          }
        }
      }

      dumpPool(pending, "pending");
      dumpPool(queued, "queued");
    }

    // ---- Network: peers ----
    let peers = [];
    try {
      peers = await provider.send("admin_peers", []);
    } catch (e) {
      console.error("[!] admin_peers RPC failed. Is admin API enabled?", e);
      peers = [];
    }

    for (const p of peers) {
      const peerId = p.id || "";
      const name = p.name || "";
      const remoteAddress = p.network?.remoteAddress || "";
      const localAddress = p.network?.localAddress || "";

      peerFile.write(
        [esc(snapshotTime), esc(peerId), esc(name), esc(remoteAddress), esc(localAddress)].join(
          ",",
        ) + "\n",
      );
    }
  }

  await oneSnapshot();
  setInterval(oneSnapshot, intervalSec * 1000);
}

// -----------------------------
// CLI Entrypoint
// -----------------------------
async function main() {
  const [, , mode, arg1, arg2] = process.argv;

  if (mode === "blocks") {
    if (!arg1 || !arg2) {
      console.error("Usage: node export_mev_data.js blocks <fromBlock> <toBlock>");
      process.exit(1);
    }
    const fromBlock = parseInt(arg1, 10);
    const toBlock = parseInt(arg2, 10);
    if (Number.isNaN(fromBlock) || Number.isNaN(toBlock) || fromBlock > toBlock) {
      console.error("Invalid block range.");
      process.exit(1);
    }
    await exportBlocks(fromBlock, toBlock);
  } else if (mode === "blocksLive") {
    const count = arg1 ? parseInt(arg1, 10) : 100;
    if (Number.isNaN(count) || count <= 0) {
      console.error("Usage: node export_mev_data.js blocksLive <count>");
      process.exit(1);
    }
    await exportBlocksLive(count);
  } else if (mode === "mempool") {
    const intervalSec = arg1 ? parseInt(arg1, 10) : 30;
    if (Number.isNaN(intervalSec) || intervalSec <= 0) {
      console.error("Usage: node export_mev_data.js mempool <intervalSeconds>");
      process.exit(1);
    }
    await snapshotMempoolAndNetwork(intervalSec);
  } else {
    console.error("Usage:");
    console.error("  node export_mev_data.js blocks <fromBlock> <toBlock>");
    console.error("  node export_mev_data.js blocksLive <count>");
    console.error("  node export_mev_data.js mempool <intervalSeconds>");
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("[!] Fatal error:", err);
  process.exit(1);
});
