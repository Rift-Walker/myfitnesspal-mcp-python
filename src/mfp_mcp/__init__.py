"""
MyFitnessPal MCP Server

A Model Context Protocol (MCP) server for interacting with MyFitnessPal data.
"""

__version__ = "1.0.0"
__author__ = "Adam"

__all__ = ["mcp", "__version__"]


def __getattr__(name):
    # Lazy so `mfp_mcp.auth` can be imported by scripts that only want the
    # shared token store, without pulling in the MCP server stack.
    if name == "mcp":
        from .server import mcp

        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
