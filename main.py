#!/usr/bin/env python3
"""
CLI Cribbage Game with Websockets
"""

import argparse
import asyncio
import sys

from server import run_server
from client import run_client

def main():
    parser = argparse.ArgumentParser(description="Cribbage CLI Game")
    parser.add_argument('--host', action='store_true', help='Run as host')
    parser.add_argument('--port', type=int, default=8765, help='Port to use')
    parser.add_argument('--host-ip', default='localhost', help='Host IP to connect to')

    args = parser.parse_args()

    if args.host:
        print("Starting as host...")
        asyncio.run(run_server(args.port))
    else:
        print("Connecting as client...")
        asyncio.run(run_client(args.host_ip, args.port))

if __name__ == "__main__":
    main()