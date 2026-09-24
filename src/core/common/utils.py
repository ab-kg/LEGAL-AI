"""
Shared Utilities
=================
Deduplicated helper functions used across the Legal AI pipeline.
"""

import socket
# ─── IPv4-Only Monkey Patch ────────────────────────────────────────
# Bypasses broken IPv6 routing that causes timeouts on some CI runners
# and local networks.  Call once at process startup.
_ipv4_patched = False
_orig_getaddrinfo = socket.getaddrinfo

def force_ipv4():
    """Patch socket.getaddrinfo to resolve IPv4 addresses only (idempotent)."""
    global _ipv4_patched
    if _ipv4_patched:
        return
    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    
    socket.getaddrinfo = _ipv4_getaddrinfo
    _ipv4_patched = True


# ─── String Helpers ────────────────────────────────────────────────

def safe_str(val):
    """Convert None to empty string, everything else to stripped str."""
    if val is None:
        return ""
    return str(val).strip()


def make_location_id(loc_dict):
    """
    Build a deterministic, collision-free Location node ID from a dict
    with optional keys: country, state, city, address.
    Returns None when all fields are empty/null.
    """
    if not loc_dict:
        return None    
    parts = [
        safe_str(loc_dict.get("country")),
        safe_str(loc_dict.get("state")),
        safe_str(loc_dict.get("city")),
        safe_str(loc_dict.get("address")),
    ]
    suffix = "_".join(p for p in parts if p)
    return f"Location_{suffix}" if suffix else None

# ─── Text Chunking ─────────────────────────────────────────────────
def chunk_text(text, chunk_size=500, overlap=100):
    """
    Split *text* into overlapping word-level chunks.

    Args:
        text: Raw text to chunk.
        chunk_size: Maximum words per chunk.
        overlap: Number of overlapping words between consecutive chunks.
    Returns:
        List of chunk strings (empty list if *text* is blank).
    """
    words = text.split()
    if not words:
        return []

    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks

# ─── Session ID Sanitization ──────────────────────────────────────
def sanitize_session_id(session_id):
    """Strip whitespace and surrounding quotes from a session ID string."""
    if not session_id:
        return session_id
    return session_id.strip().strip('"').strip("'")