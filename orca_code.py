"""
Orca Code — desktop AI assistant.

Usage:
    python orca_code.py              Interactive mode
    python orca_code.py --version    Show version
    python orca_code.py --help       Show help
    python orca_code.py --no-mcp     Skip MCP tool loading
"""

import argparse
import sys

from orca_code import __version__
from orca_code.main import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="orca_code",
        description="Orca Code — desktop AI assistant with 58+ tools.",
    )
    parser.add_argument(
        "--version", "-V", action="version",
        version=f"Orca Code v{__version__}",
    )
    parser.add_argument(
        "--no-mcp", action="store_true",
        help="Skip MCP tool loading on startup",
    )
    args = parser.parse_args()

    if args.no_mcp:
        sys.argv.append("--no-mcp")

    main()
