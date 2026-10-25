"""Backward-compatible alias; model verification now uses Mesh API, not Bedrock generation."""
from verify_mesh import main

if __name__ == "__main__":
    raise SystemExit(main())
