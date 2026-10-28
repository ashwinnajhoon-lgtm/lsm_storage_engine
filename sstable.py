"""Immutable SSTables with a sparse index and an optional Bloom filter."""
import base64
import hashlib
import json
import math
import os


def _fsync_directory(directory: str):
    """Best-effort directory sync after atomic renames (mainly Unix)."""
    if os.name == "nt":
        return
    try:
        fd = os.open(directory or ".", getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _hashes(key: str, bit_count: int, hash_count: int):
    """Yield deterministic double-hash positions; stable across restarts."""
    raw = key.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    h1 = int.from_bytes(digest[:16], "big")
    h2 = int.from_bytes(digest[16:], "big") | 1
    for i in range(hash_count):
        yield (h1 + i * h2) % bit_count


class BloomFilter:
    """Compact membership hint. It may say 'maybe', never 'definitely not' incorrectly."""
    def __init__(self, expected_items=1, false_positive_rate=0.01, bits=None, hash_count=None):
        expected_items = max(1, expected_items)
        self.bit_count = max(8, int(-expected_items * math.log(false_positive_rate) / (math.log(2) ** 2)))
        self.hash_count = max(1, int((self.bit_count / expected_items) * math.log(2)))
        self.bits = bytearray((self.bit_count + 7) // 8) if bits is None else bytearray(bits)
        if hash_count is not None:
            self.hash_count = hash_count

    def add(self, key: str):
        for pos in _hashes(key, self.bit_count, self.hash_count):
            self.bits[pos // 8] |= 1 << (pos % 8)

    def might_contain(self, key: str) -> bool:
        return all(self.bits[pos // 8] & (1 << (pos % 8)) for pos in _hashes(key, self.bit_count, self.hash_count))

    def to_record(self):
        return {"bit_count": self.bit_count, "hash_count": self.hash_count,
                "bits": base64.b64encode(self.bits).decode("ascii")}

    @staticmethod
    def from_record(record):
        bit_count = record["bit_count"]
        hash_count = record["hash_count"]
        bits = base64.b64decode(record["bits"], validate=True)
        if not isinstance(bit_count, int) or bit_count < 1 or not isinstance(hash_count, int) or hash_count < 1:
            raise ValueError("Invalid Bloom filter parameters")
        if len(bits) != (bit_count + 7) // 8:
            raise ValueError("Invalid Bloom filter bit length")
        result = BloomFilter(bits=bits, hash_count=hash_count)
        result.bit_count = bit_count
        return result


class SSTableWriter:
    """Write sorted key/value records, sparse-index offsets, and a Bloom filter."""
    @staticmethod
    def flush_to_disk(filepath: str, memtable_items, index_interval: int = 100):
        if index_interval < 1:
            raise ValueError("index_interval must be at least 1")

        index_path = filepath + ".index"
        bloom_path = filepath + ".bloom"
        temp_data, temp_index, temp_bloom = filepath + ".tmp", index_path + ".tmp", bloom_path + ".tmp"
        directory = os.path.dirname(os.path.abspath(filepath))
        # Materialize once because we need a count to size the Bloom filter.
        items = list(memtable_items)
        items.sort(key=lambda pair: pair[0])
        bloom = BloomFilter(expected_items=len(items))
        sparse_index = []
        try:
            # Binary I/O makes saved offsets exact UTF-8 byte offsets, including Unicode.
            with open(temp_data, "wb") as data_file:
                for i, (key, value) in enumerate(items):
                    if i % index_interval == 0:
                        sparse_index.append({"key": key, "offset": data_file.tell()})
                    record = json.dumps({"key": key, "value": value}, ensure_ascii=False,
                                        separators=(",", ":")).encode("utf-8") + b"\n"
                    data_file.write(record)
                    bloom.add(key)
                data_file.flush()
                os.fsync(data_file.fileno())

            with open(temp_index, "wb") as index_file:
                for entry in sparse_index:
                    index_file.write(json.dumps(entry, ensure_ascii=False,
                                                separators=(",", ":")).encode("utf-8") + b"\n")
                index_file.flush()
                os.fsync(index_file.fileno())

            with open(temp_bloom, "wb") as bloom_file:
                bloom_file.write(json.dumps(bloom.to_record(), separators=(",", ":")).encode("utf-8") + b"\n")
                bloom_file.flush()
                os.fsync(bloom_file.fileno())

            # Publish helper files first and the .db file last as the commit marker.
            os.replace(temp_index, index_path)
            os.replace(temp_bloom, bloom_path)
            _fsync_directory(directory)
            os.replace(temp_data, filepath)
            _fsync_directory(directory)
        except Exception:
            for path in (temp_data, temp_index, temp_bloom):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
            raise


class SSTableReader:
    """Search SSTable with Bloom-filter rejection and sparse-index binary search."""
    @staticmethod
    def iter_items(filepath: str):
        """Yield all records in order; raise on corruption (important for compaction)."""
        with open(filepath, "rb") as data_file:
            for line_number, raw_line in enumerate(data_file, start=1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                    key, value = record["key"], record["value"]
                    if not isinstance(key, str) or not isinstance(value, str):
                        raise ValueError("key/value must be strings")
                except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise ValueError(f"Corrupt SSTable {filepath} at line {line_number}") from exc
                yield key, value

    @staticmethod
    def get(filepath: str, target_key: str):
        index_path = filepath + ".index"
        if not os.path.isfile(filepath) or not os.path.isfile(index_path):
            return None

        # A valid Bloom filter can rule out a key without reading the SSTable.
        # Missing/corrupt Bloom files are only a performance issue, so fall back safely.
        bloom_path = filepath + ".bloom"
        if os.path.isfile(bloom_path):
            try:
                with open(bloom_path, "r", encoding="utf-8") as bloom_file:
                    bloom = BloomFilter.from_record(json.load(bloom_file))
                if not bloom.might_contain(target_key):
                    return None
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass

        sparse_index = []
        try:
            with open(index_path, "r", encoding="utf-8") as index_file:
                for line in index_file:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    key, offset = entry["key"], entry["offset"]
                    if not isinstance(key, str) or not isinstance(offset, int) or offset < 0:
                        return None
                    sparse_index.append((key, offset))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        if not sparse_index:
            return None

        # Find the last indexed key <= target_key.
        left, right, best = 0, len(sparse_index) - 1, -1
        while left <= right:
            mid = (left + right) // 2
            if sparse_index[mid][0] <= target_key:
                best = mid
                left = mid + 1
            else:
                right = mid - 1
        if best == -1:
            return None

        try:
            with open(filepath, "rb") as data_file:
                data_file.seek(sparse_index[best][1])
                for raw_line in data_file:
                    if not raw_line.strip():
                        continue
                    try:
                        record = json.loads(raw_line.decode("utf-8"))
                        key, value = record["key"], record["value"]
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
                        return None
                    if key == target_key:
                        return value
                    if key > target_key:
                        break
        except OSError:
            return None
        return None
