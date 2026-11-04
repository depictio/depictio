"""Expose a loopback-only port on a LAN address.

``depictio local up`` binds every service to 127.0.0.1. To let another machine
(or another instance addressed by its LAN IP) reach the API, forward
``<lan ip>:<port>`` to ``127.0.0.1:<port>``:

    python forward.py 192.168.1.20 18059

Plain TCP, one thread per connection; stops on Ctrl-C.
"""

from __future__ import annotations

import socket
import sys
import threading


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while chunk := src.recv(65536):
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _serve(client: socket.socket, port: int) -> None:
    try:
        upstream = socket.create_connection(("127.0.0.1", port))
    except OSError:
        client.close()
        return
    threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
    _pipe(upstream, client)


def main(host: str, port: int, upstream_port: int | None = None) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(64)
    print(f"forwarding {host}:{port} -> 127.0.0.1:{upstream_port or port}", flush=True)
    while True:
        client, _ = server.accept()
        threading.Thread(target=_serve, args=(client, upstream_port or port), daemon=True).start()


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit("usage: forward.py <lan ip> <port> [<upstream port>]")
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) == 4 else None)
