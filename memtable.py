import random

class SkipListNode:
    """Represents a single key-value node inside the Skip List."""
    def __init__(self, key: str, value: str, level: int):
        self.key = key
        self.value = value
        # 'forward' is an array of pointers pointing to the next node at each level.
        self.forward = [None] * level


class MemTable:
    """In-memory sorted storage engine component using a Skip List."""
    def __init__(self, max_level: int = 16, p: float = 0.5):
        self.max_level = max_level
        self.p = p  # Probability for coin-tossing node levels
        self.level = 1  # Current max level active in the skip list
        
        # Dummy head node to anchor the multi-level structure
        self.head = SkipListNode(None, None, self.max_level)
        
        # Track approximate memory size in bytes to trigger SSTable flushes later
        self.size_bytes = 0

    def _random_level(self) -> int:
        """Probabilistically determines the height of a new node (Coin Toss)."""
        lvl = 1
        while random.random() < self.p and lvl < self.max_level:
            lvl += 1
        return lvl


    def put(self, key: str, value: str):
        """Inserts or updates a key-value pair in sorted order ($O(\log n)$)."""
        update = [None] * self.max_level
        curr = self.head

        # 1. Traverse down and right to find the insertion position
        for i in range(self.level - 1, -1, -1):
            while curr.forward[i] and curr.forward[i].key < key:
                 curr = curr.forward[i]
            update[i] = curr  #here update[i] is pointer which point the node which come before that

        curr = curr.forward[0]
        
        

        # 2. If key already exists, update its value (In-place update)
        if curr and curr.key == key:
            # Adjust byte tracking difference
            self.size_bytes += len(value) - len(curr.value)
            curr.value = value # current islike NODE type;
            return

        # 3. If key doesn't exist, generate a random level for the new node
        r_level = self._random_level()

        # If the generated level exceeds the current max level, expand update pointers
        if r_level > self.level:
            for i in range(self.level, r_level):
                update[i] = self.head
            self.level = r_level

        # 4. Create the new node and splice it into the linked list pointers
        new_node = SkipListNode(key, value, r_level)
        for i in range(r_level):
            new_node.forward[i] = update[i].forward[i]
            update[i].forward[i] = new_node

        # Track approximate size growth (key + value byte length)
        self.size_bytes += len(key.encode('utf-8')) + len(value.encode('utf-8'))

    def get(self, key: str) -> str:
        """Searches for a key in $O(\log n)$ time. Returns value or None."""
        curr = self.head

        # Traverse from top level down to level 0
        for i in range(self.level - 1, -1, -1):
            while curr.forward[i] and curr.forward[i].key < key:
                 curr = curr.forward[i]

        curr = curr.forward[0]

        # Check if we landed on the exact key
        if curr and curr.key == key:
            return curr.value
        
        return None

    def items(self):
        """Yields all key-value pairs in sorted order (used when flushing to SSTable)."""
        curr = self.head.forward[0]
        while curr:
            yield curr.key, curr.value
            curr = curr.forward[0]

    def clear(self):
        """Resets the MemTable back to an empty state."""
        self.head = SkipListNode(None, None, self.max_level)
        self.level = 1
        self.size_bytes = 0


# --- Self-Verification Test Script ---
if __name__ == "__main__":
    print("--- Testing MemTable (Skip List) ---")
    memtable = MemTable()

    # Test Puts (Out of order insertion to verify sorting)
    memtable.put("user:3", "Charlie")
    memtable.put("user:1", "Ayush")
    memtable.put("user:2", "Bob")
    memtable.put("user:1", "Ayush Updated") # Test update

    # Test Gets
    print(f"Get 'user:1': {memtable.get('user:1')}") # Expected: Ayush Updated
    print(f"Get 'user:2': {memtable.get('user:2')}") # Expected: Bob
    print(f"Get 'user:99': {memtable.get('user:99')}") # Expected: None

    # Test Sorted Iteration (Crucial for SSTable Flushes)
    print("\n--- Sorted Iteration Check ---")
    for k, v in memtable.items():
        print(f"Key: {k} | Value: {v}")

    print(f"\nMemTable approximate size in bytes: {memtable.size_bytes}")
    print("MemTable verification complete!")
