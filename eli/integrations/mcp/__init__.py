"""Model Context Protocol integration.

Two directions, deliberately separated:

* ``client`` — ELI as an MCP *host*: it launches configured MCP servers and gains
  their tools, so the capability surface grows without a code change here.
* ``server`` — ELI as an MCP *server*: its own actions exposed to any other MCP
  client, which is what makes it a platform rather than an application.

Transport is stdio only. An MCP server is a local subprocess, so tool use stays
inside the offline-by-default posture: nothing here opens a socket, and remote
(HTTP/SSE) transports are intentionally not implemented rather than added and
silently routed around netguard.
"""
from __future__ import annotations

__all__ = ["client", "server"]
