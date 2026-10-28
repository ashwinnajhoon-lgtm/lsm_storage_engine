# LSM-Tree Storage Engine (learning project)

A small, educational key-value database built around a Skip List MemTable, a Write-Ahead Log (WAL), immutable Sorted String Tables (SSTables), sparse indexes, Bloom filters, and manual compaction.

## Files
- `memtable.py` — original Skip List implementation; class/method structure retained.
- `wal.py` — retains the `WAL` class and `append`, `recover`, `clear`, `close` methods. New records use JSON Lines so keys and values can safely contain colons and newlines; legacy colon-delimited WAL lines are also read where possible.
- `sstable.py` — sorted JSON Lines records, sparse index (`.index`), Bloom filter (`.bloom`), atomic temporary-file publication, and lookup.
- `storage_engine.py` — startup recovery, PUT/GET/DELETE, flush, SSTable discovery, and compaction.
- `main.py` — FastAPI endpoints.
- `index.html` — browser dashboard, including PUT, GET, DELETE, FLUSH, and COMPACT controls.
- `test_recovery.py` — disposable-directory regression tests.
- `benchmark.py` — basic local performance measurement.

## Install and run
Use Python 3.10+.

```bash
python -m pip install fastapi uvicorn
python -m uvicorn main:app --reload
```

Open `index.html` in a browser. API docs: http://127.0.0.1:8000/docs.

## API endpoints
- `POST /put` JSON body: `{"key":"user:1","value":"Ayush"}`
- `GET /get/{key}` — read a key (the dashboard URL-encodes keys).
- `DELETE /delete/{key}` — write a delete tombstone.
- `POST /flush` — force MemTable contents into an SSTable.
- `POST /compact` — merge all committed SSTables into one.
- `GET /health` — basic engine status.

## Data structures and algorithms
- **Skip List MemTable:** keeps in-memory keys ordered; expected O(log n) search/insert.
- **WAL:** append and `fsync` before applying writes to the MemTable.
- **SSTable:** immutable sorted key/value records on disk.
- **Sparse index:** stores every 100th key by default and its exact byte offset. Lookup binary-searches this index, then scans only a small range.
- **Bloom filter:** quickly says a key is definitely absent or possibly present. False positives are possible; false negatives should not occur when the filter is valid. Missing/corrupt filters fall back to the index scan.
- **Compaction:** visits SSTables newest-first; the newest version wins for each key. It writes a new merged SSTable before deleting old files. Tombstones are kept in the compacted output so an interrupted old-file cleanup cannot cause deleted keys to reappear.

## Recovery and durability notes
1. Each PUT/DELETE is appended to the WAL and synced before the MemTable is changed.
2. SSTable data, sparse index, and Bloom filter are written to temporary files and synced.
3. The helper files are renamed first; the final `.db` file is published last as the table's commit marker.
4. The WAL is cleared only after the new SSTable has been published successfully.
5. Startup discovers table/index pairs and replays any remaining WAL records.
6. Compaction publishes its merged table before deleting older files. Tombstones are retained to protect against interrupted cleanup.

This is a **learning project, not a production database**. It does not use a manifest, checksummed blocks, a lock for multiple processes, or a formal transactional multi-file commit protocol. Filesystem behavior varies, and no claim of guaranteed survival under every hardware/power failure is made. Do not use it for important data. Always test in a disposable directory and back up any existing `data/` directory before migrating file formats.

## Tests and benchmark
```bash
python test_recovery.py
python benchmark.py
```
The test creates and removes a temporary directory and checks WAL recovery, Unicode/separator-containing keys, sparse-index/Bloom lookup, updates, deletes, compaction, and restart behavior. The benchmark is a simple local comparison aid; its results depend on your machine, Python version, and disk.

## File-format migration
New SSTables use JSON Lines and companion `.index` and `.bloom` files. Older colon-delimited SSTables from an earlier version are not compatible with this format. Back up and use a fresh data directory for this version unless you implement a migration tool.

## Reserved value
`[DELETED]` is used internally as the tombstone marker by the existing MemTable interface, so the engine rejects that exact value in `put`. A future version could replace this with an explicit typed record format to avoid reserving a user value.
