"""
TSRC (The Stellar Registry Committee) local tooling package.

Phase 1 responsibilities:
- Read entry JSON from /public/data/entries/<ID>.json
- Generate a fully-regenerable PDF certificate using only that JSON
- Write PDF output to /public/certificates/<ID>/certificate.pdf
"""

__all__ = ["config"]
__version__ = "0.1.0"
