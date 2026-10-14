#!/usr/bin/env python3
"""Local, persistent SSH bridge for an AR730 operator and an AI assistant.

The service listens only on a Unix-domain socket owned by the current user.
It keeps one interactive SSH shell open, preserves router prompts/views, and
records every forwarded terminal command and reply in a local JSONL transcript.
Credentials are loaded from an ignored 0600 JSON file and never written to the
transcript, standard output, or application settings.

This bridge starts read-only.  A user must deliberately set ``allow_write`` to
true in the local configuration before a non-display command can be forwarded.
Even then, callers must send an explicit ``write`` request rather than having
ordinary reads accidentally mutate a production router.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import stat
import sys
import threading
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ar730_manager import RouterError, RouterSession, mask_password  # noqa: E402


DEFAULT_CONFIG = os.path.join(ROOT, "router_agent.local.json")


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def socket_path(config_path):
    # The path stays outside the repository so a checkout cannot accidentally
    # publish a live control endpoint. UID makes it private to this login.
    token = uuid.uuid5(uuid.NAMESPACE_URL, os.path.abspath(config_path)).hex[:12]
    return os.path.join("/tmp", "ar730-agent-%s-%s.sock" % (os.getuid(), token))


def load_config(path):
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError as exc:
        raise RuntimeError("Cannot read local router configuration: %s" % exc)
    if mode & 0o077:
        raise RuntimeError("Refusing to use %s: run chmod 600 %s" % (path, path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Invalid local router configuration: %s" % exc)
    for key in ("host", "username", "password"):
        value = str(config.get(key, "")).strip()
        if not value or value.startswith("PUT_ROUTER_"):
            raise RuntimeError("Set %s in %s before starting the bridge." % (key, path))
    try:
        config["port"] = int(config.get("port", 22))
    except (TypeError, ValueError):
        raise RuntimeError("Router port must be a number.")
    log_name = str(config.get("session_log") or "router_agent_sessions.jsonl")
    if os.path.isabs(log_name) or os.path.basename(log_name) != log_name:
        raise RuntimeError("session_log must be a filename in the repository root.")
    config["log_path"] = os.path.join(ROOT, log_name)
    return config


def write_record(path, session_id, event, **data):
    record = {"at": utc_now(), "session": session_id, "event": event}
    record.update({key: mask_password(str(value)) for key, value in data.items()})
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def is_read_only(command):
    command = (command or "").strip().lower()
    return (command.startswith("display ") or command.startswith("ping ") or
            command in {"screen-length 0 temporary", "return"})


class Bridge(object):
    def __init__(self, config):
        self.config = config
        self.session_id = uuid.uuid4().hex
        # RouterSession also logs its housekeeping command (screen-length) and
        # any prompt details. Keep that byte-oriented transcript alongside the
        # structured command/reply records below.
        self.router = RouterSession(self._router_log)
        self.lock = threading.Lock()

    def audit(self, event, **data):
        write_record(self.config["log_path"], self.session_id, event, **data)

    def _router_log(self, text):
        self.audit("terminal", transcript=text)

    def connect(self):
        self.audit("session_start", host=self.config["host"], port=self.config["port"],
                   username=self.config["username"], write_enabled=self.config.get("allow_write", False))
        self.router.connect(self.config["host"], self.config["port"],
                            self.config["username"], self.config["password"])
        self.audit("session_connected", hostname=self.router.hostname)

    def status(self):
        return {"connected": bool(self.router.connected), "hostname": self.router.hostname,
                "session": self.session_id, "write_enabled": bool(self.config.get("allow_write"))}

    def send(self, command, write=False):
        command = (command or "").strip()
        if not command:
            raise RuntimeError("A router command is required.")
        read_only = is_read_only(command)
        if not read_only and not (write and self.config.get("allow_write")):
            raise RuntimeError("Write blocked: set allow_write=true locally and make an explicit write request.")
        with self.lock:
            self.audit("command", command=command, mode="write" if not read_only else "read")
            reply = self.router.send(command, answer_yes=False)
            self.audit("reply", command=command, reply=reply)
        return reply

    def close(self, reason="requested"):
        self.audit("session_end", reason=reason)
        self.router.close()


def response(conn, payload):
    conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))


def serve(config_path):
    config = load_config(config_path)
    path = socket_path(config_path)
    if os.path.exists(path):
        raise RuntimeError("Bridge socket already exists: %s" % path)
    bridge = Bridge(config)
    bridge.connect()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(path)
        os.chmod(path, 0o600)
        server.listen(4)
        print(json.dumps({"ready": True, "socket": path, **bridge.status()}, ensure_ascii=False), flush=True)
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    raw = conn.makefile("r", encoding="utf-8").readline()
                    request = json.loads(raw)
                    action = request.get("action")
                    if action == "status":
                        response(conn, {"ok": True, "result": bridge.status()})
                    elif action == "send":
                        reply = bridge.send(request.get("command", ""), bool(request.get("write")))
                        response(conn, {"ok": True, "result": {"reply": reply}})
                    elif action == "stop":
                        bridge.close()
                        response(conn, {"ok": True, "result": {"stopped": True}})
                        return
                    else:
                        response(conn, {"ok": False, "error": "Unknown action."})
                except (RouterError, RuntimeError, ValueError, OSError) as exc:
                    bridge.audit("request_error", error=str(exc))
                    response(conn, {"ok": False, "error": str(exc)})
    finally:
        bridge.close("bridge_exit")
        server.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def request(config_path, payload):
    path = socket_path(config_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(path)
        client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        data = client.makefile("r", encoding="utf-8").readline()
    finally:
        client.close()
    print(data, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("serve")
    sub.add_parser("status")
    send = sub.add_parser("send")
    send.add_argument("command")
    send.add_argument("--write", action="store_true", help="Explicitly request a non-read command.")
    sub.add_parser("stop")
    args = parser.parse_args()
    config_path = os.path.abspath(args.config)
    if args.action == "serve":
        serve(config_path)
    elif args.action == "status":
        request(config_path, {"action": "status"})
    elif args.action == "send":
        request(config_path, {"action": "send", "command": args.command, "write": args.write})
    else:
        request(config_path, {"action": "stop"})


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        sys.stderr.write("Router agent bridge: %s\n" % exc)
        sys.exit(2)
