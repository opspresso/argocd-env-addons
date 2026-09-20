#!/usr/bin/env python3
"""Keep local-only service forwards open on OrbStack or Docker Desktop."""

import argparse
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import yaml

from runtime import resolve_context


CONNECTIONS = Path(__file__).with_name("connections.yaml")


def command(context, service):
    return ["kubectl", "--context", context, "--namespace", service["namespace"],
            "port-forward", "--address", "127.0.0.1", f"service/{service['service']}", *service["ports"]]


def check_ports(services):
    sockets = []
    try:
        for service in services.values():
            for mapping in service["ports"]:
                port = int(mapping.split(":")[0])
                listener = socket.socket()
                sockets.append(listener)
                try:
                    listener.bind(("127.0.0.1", port))
                except OSError as error:
                    raise RuntimeError(f"Local port {port} is unavailable; stop its existing listener before connecting") from error
    finally:
        for listener in sockets:
            listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", help="orbstack or docker-desktop (default: KUBE_CONTEXT/current context)")
    parser.add_argument("--only", nargs="+", help="forward only the named services")
    parser.add_argument("--list", action="store_true", help="print connection URLs without starting forwards")
    args = parser.parse_args()
    services = yaml.safe_load(CONNECTIONS.read_text())
    if args.only:
        unknown = set(args.only) - set(services)
        if unknown:
            parser.error(f"Unknown services: {', '.join(sorted(unknown))}")
        services = {name: services[name] for name in args.only}
    for name, service in services.items():
        print(f"{name}: {service['url']}", flush=True)
    if args.list:
        return 0
    context = resolve_context(args.context)
    check_ports(services)
    children = []

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        for name, service in services.items():
            children.append((name, subprocess.Popen(command(context, service))))
        while True:
            for name, child in children:
                if child.poll() is not None:
                    raise RuntimeError(f"{name} forwarding stopped (exit {child.returncode}); check the Pod and rerun this command")
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for _, child in children:
            if child.poll() is None:
                child.terminate()
        for _, child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
