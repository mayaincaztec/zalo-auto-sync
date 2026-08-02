"""
Hasher Utility Module
Calculates SHA-256 file hashes in chunks for memory-efficient duplicate detection.
"""

import hashlib
import os


def calculate_sha256(filepath: str, chunk_size: int = 65536) -> str:
    """Calculates SHA-256 hash of a file reading in binary chunks.
    
    Args:
        filepath: Absolute path to the file.
        chunk_size: Buffer size in bytes (default: 64KB).
        
    Returns:
        Hexadecimal SHA-256 string.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()
