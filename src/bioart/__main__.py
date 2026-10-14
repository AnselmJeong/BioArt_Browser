import argparse
import os
import socket
from .config import prepare, workspace, atomic_json


def main():
    parser = argparse.ArgumentParser(description="BioArt Browser local catalog")
    parser.add_argument(
        "command", choices=["inventory", "metadata", "reparse", "serve", "mcp"]
    )
    parser.add_argument("--workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ready-file")
    parser.add_argument("--ready-stdout", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.parent_pid:
        import threading
        import time

        def watch_parent():
            while True:
                if os.getppid() != args.parent_pid:
                    os._exit(0)
                time.sleep(1)

        threading.Thread(target=watch_parent, daemon=True).start()
    if args.workspace:
        os.environ["BIOART_WORKSPACE"] = args.workspace
    prepare()
    if args.command == "inventory":
        from .pipeline import inventory

        inventory()
    elif args.command == "metadata":
        from .pipeline import collect_metadata

        collect_metadata(args.limit)
    elif args.command == "reparse":
        from .pipeline import reparse_metadata

        print(reparse_metadata())
    elif args.command == "mcp":
        from .mcp_server import mcp

        mcp.run(transport="stdio")
    else:
        import uvicorn
        from .server import app

        sock = socket.socket()
        sock.bind(("127.0.0.1", args.port))
        sock.listen(128)
        if args.ready_stdout:
            import json

            print("BIOART_READY " + json.dumps(dict(port=sock.getsockname()[1], pid=os.getpid())), flush=True)
        if args.ready_file:
            atomic_json(
                workspace() / "state" / args.ready_file,
                dict(port=sock.getsockname()[1], pid=os.getpid()),
            )
        uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=sock.getsockname()[1], log_level="warning"
            )
        ).run(sockets=[sock])


if __name__ == "__main__":
    main()
