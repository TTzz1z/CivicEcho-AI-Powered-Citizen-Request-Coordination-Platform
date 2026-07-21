"""Minimal clamd INSTREAM mock for CI production-compose.

Responds:
- EICAR payload -> stream: Eicar-Test-Signature FOUND
- anything else -> stream: OK

Accepts both null-terminated (zINSTREAM\\0) and newline-terminated commands.
"""
from __future__ import annotations

import socketserver
import struct


EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class ClamdHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        sock = self.request
        sock.settimeout(10)
        cmd = b""
        while len(cmd) < 64:
            chunk = sock.recv(1)
            if not chunk:
                return
            cmd += chunk
            # Stock clamd client uses zINSTREAM\0; some tools use nINSTREAM\n.
            if cmd.endswith(b"\0") or cmd.endswith(b"\n"):
                break
        if b"INSTREAM" not in cmd.upper():
            sock.sendall(b"ERROR\n")
            return
        data = bytearray()
        while True:
            header = sock.recv(4)
            if len(header) < 4:
                break
            (size,) = struct.unpack("!I", header)
            if size == 0:
                break
            remaining = size
            while remaining > 0:
                part = sock.recv(min(65536, remaining))
                if not part:
                    remaining = 0
                    break
                data.extend(part)
                remaining -= len(part)
        if EICAR in data or b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data:
            sock.sendall(b"stream: Eicar-Test-Signature FOUND\0")
        else:
            sock.sendall(b"stream: OK\0")


if __name__ == "__main__":
    server = socketserver.ThreadingTCPServer(("0.0.0.0", 3310), ClamdHandler)
    server.allow_reuse_address = True
    print("clamd-mock listening on 0.0.0.0:3310", flush=True)
    server.serve_forever()
