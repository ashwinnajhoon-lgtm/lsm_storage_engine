import json
import os

class WAL:
    def __init__(self, filepath="wal.log"):
        self.filepath = filepath
        # Mode "a" = append-only; preserves past writes and creates file if missing
        self.file = open(self.filepath, "a", encoding="utf-8")

    def append(self, op_type: str, key: str, value: str = ""):
        """Append one durable operation to the WAL.

        JSON Lines lets keys and values safely contain colons, tabs, and newlines.
        The public WAL structure and method names remain the same.
        """
        log_entry = json.dumps(
            {"op": op_type, "key": key, "value": value},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.file.write(log_entry + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def recover(self):
        """Read saved operations during startup to restore in-memory state."""
        if not os.path.exists(self.filepath):
            return []

        recovered_records = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                clean_line = line.strip()
                if not clean_line:
                    continue

                # Current format: one JSON object per line.
                try:
                    record = json.loads(clean_line)
                    if isinstance(record, dict):
                        op = record.get("op")
                        key = record.get("key")
                        value = record.get("value", "")
                        if isinstance(op, str) and isinstance(key, str) and isinstance(value, str):
                            recovered_records.append((op, key, value))
                            continue
                except (json.JSONDecodeError, TypeError):
                    pass

                # Backward compatibility for old records such as PUT:key:value.
                # Old colon-delimited records cannot unambiguously represent a colon
                # inside the key; new records use JSON and do not have that limitation.
                parts = clean_line.split(":", 2)
                if len(parts) == 3 and parts[0] in ("PUT", "DEL", "DELETE"):
                    recovered_records.append((parts[0], parts[1], parts[2]))
                # Malformed/truncated records are ignored, including an incomplete tail.

        return recovered_records

    def clear(self):
        """Clear the log after its records have been safely persisted to an SSTable."""
        self.file.close()
        self.file = open(self.filepath, "w", encoding="utf-8")
        self.file.truncate(0)
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        self.file = open(self.filepath, "a", encoding="utf-8")

    def close(self):
        """Cleanly releases the OS file descriptor."""
        if not self.file.closed:
            self.file.close()


if __name__ == "__main__":
    print("--- 1. Testing WAL Append ---")
    log = WAL("demo_wal.log")
    log.append("PUT", "user:1", "Ayush")
    log.append("PUT", "user:2", "SystemCallers")
    log.append("DEL", "user:1", "")
    log.close()
    print("Logged 3 operations successfully.")

    print("\n--- 2. Testing Crash Recovery Read ---")
    recovery_log = WAL("demo_wal.log")
    records = recovery_log.recover()
    for op, key, val in records:
        print(f"Recovered -> Op: {op:<6} | Key: {key:<8} | Value: {val}")

    print("\n--- 3. Testing Clear / Reset ---")
    recovery_log.clear()
    recovery_log.close()
    check_log = WAL("demo_wal.log")
    remaining = check_log.recover()
    print("Records remaining after clear:", len(remaining))
    check_log.close()
    if os.path.exists("demo_wal.log"):
        os.remove("demo_wal.log")
    print("\nWAL verification complete!")
