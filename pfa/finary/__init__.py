"""Finary access: OAuth (Clerk), REST client, MCP client, and raw -> canonical mapping.

Deterministic and stdlib-only, like the rest of `pfa`. No agent involved: this is what replaces
the `/snapshot` skill's fetch-and-map steps so the pipeline can run from cron.
"""
MCP_URL = "https://public-api.finary.com/mcp"
API_BASE = "https://public-api.finary.com"
