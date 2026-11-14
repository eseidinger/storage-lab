"""NATS accounts, JetStream streams, and password users managed by config reload."""

import fcntl
import hashlib
import hmac
import json
import os
import socket
import ssl
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .settings import Settings, get_settings


def _hash_password(secret: str) -> str:
    result = subprocess.run(["nats", "server", "passwd", "--pass", secret],
                            capture_output=True, text=True, check=True, timeout=20)
    value = result.stdout.strip()
    if not value.startswith("$2"):
        raise RuntimeError("NATS password hashing failed")
    return value


class NatsConnection:
    def __init__(self, host: str, username: str, password: str, ca_file: str):
        raw = socket.create_connection((host, 4222), timeout=10)
        self.socket = ssl.create_default_context(cafile=ca_file).wrap_socket(raw, server_hostname="localhost")
        self.socket.settimeout(15)
        self.stream = self.socket.makefile("rb")
        info = self._line()
        if not info.startswith(b"INFO "):
            raise RuntimeError("NATS did not send server info")
        self.server_id = json.loads(info[5:])["server_id"]
        self._sid = 0
        options = json.dumps({"user": username, "pass": password, "verbose": False, "pedantic": True})
        self.socket.sendall(f"CONNECT {options}\r\nPING\r\n".encode())
        while self._line() != b"PONG":
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()
        self.socket.close()

    def _line(self) -> bytes:
        line = self.stream.readline().rstrip(b"\r\n")
        if line.startswith(b"-ERR") or not line:
            raise RuntimeError(f"NATS protocol error: {line[:120].decode(errors='replace')}")
        if line == b"PING":
            self.socket.sendall(b"PONG\r\n")
            return self._line()
        return line

    def request(self, subject: str, body: dict | None = None, *, allow_error: bool = False) -> dict:
        inbox = f"_INBOX.{uuid4().hex}"
        self._sid += 1
        sid = self._sid
        payload = json.dumps(body or {}, separators=(",", ":")).encode()
        self.socket.sendall(f"SUB {inbox} {sid}\r\nPUB {subject} {inbox} {len(payload)}\r\n".encode()
                            + payload + b"\r\nPING\r\n")
        while True:
            line = self._line()
            if line.startswith(b"MSG "):
                size = int(line.split()[-1])
                message = json.loads(self.stream.read(size))
                if self.stream.read(2) != b"\r\n":
                    raise RuntimeError("Malformed NATS message")
                self.socket.sendall(f"UNSUB {sid}\r\n".encode())
                if message.get("error") and not allow_error:
                    raise RuntimeError(f"NATS request failed: {message['error']}")
                return message


class NatsAdapter:
    def __init__(self, settings: Settings):
        if not settings.nats_config_dir or not settings.nats_sys_password or not settings.nats_tls_ca:
            raise RuntimeError("NATS administration is not configured")
        self.settings = settings
        self.directory = Path(settings.nats_config_dir)
        self.directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _state(self):
        lock = self.directory / "state.lock"
        with lock.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            path = self.directory / "state.json"
            state = json.loads(path.read_text()) if path.exists() else {
                "sys_hash": _hash_password(self.settings.nats_sys_password), "accounts": {}}
            yield state

    def _render(self, state: dict) -> str:
        accounts = {"SYS": {"users": [{"user": "sl_system", "password": state["sys_hash"]}]}}
        for project_id, account in sorted(state["accounts"].items()):
            prefix = f"sl_{project_id}"
            users = []
            for username, password_hash in sorted(account["users"].items()):
                users.append({"user": username, "password": password_hash, "permissions": {
                    "publish": {"allow": [f"{prefix}.>", "$JS.API.>", "_INBOX.>"]},
                    "subscribe": {"allow": [f"{prefix}.>", "$JS.ACK.>", "_INBOX.>"]},
                }})
            accounts[prefix] = {"jetstream": "enabled", "users": users}
        config = {
            "server_name": "storage-lab-nats", "listen": "0.0.0.0:4222",
            "jetstream": {"store_dir": "/data/jetstream", "max_mem_store": 1073741824,
                          "max_file_store": 10737418240},
            "tls": {"cert_file": "/certs/postgres.crt", "key_file": "/certs/postgres.key",
                    "ca_file": "/certs/postgres.crt", "handshake_first": True},
            "system_account": "SYS", "accounts": accounts,
            "authorization": {"users": [{"user": "sl_sealed_global", "password": state["sys_hash"]}]},
        }
        return json.dumps(config, indent=2) + "\n"

    def _save(self, state: dict, *, reload: bool = True) -> None:
        state_path = self.directory / "state.json"
        config_path = self.directory / "nats.conf"
        old_state = state_path.read_bytes() if state_path.exists() else None
        old_config = config_path.read_bytes() if config_path.exists() else None
        for path, content, mode in ((state_path, json.dumps(state).encode(), 0o600),
                                    (config_path, self._render(state).encode(), 0o644)):
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_bytes(content)
            temp.chmod(mode)
            os.replace(temp, path)
        if reload:
            try:
                with self._connect("sl_system", self.settings.nats_sys_password) as connection:
                    connection.request(f"$SYS.REQ.SERVER.{connection.server_id}.RELOAD")
            except Exception:
                for path, old in ((state_path, old_state), (config_path, old_config)):
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(old)
                raise

    def _connect(self, username: str, password: str) -> NatsConnection:
        return NatsConnection(self.settings.nats_admin_host, username, password, self.settings.nats_tls_ca)

    def _admin_password(self, project_id: str) -> str:
        return hmac.new(self.settings.nats_sys_password.encode(), project_id.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _name(project_id: str) -> str:
        if len(project_id) != 32 or not all(char in "0123456789abcdef" for char in project_id):
            raise ValueError("Invalid project ID")
        return f"sl_{project_id}"

    def initialize(self) -> None:
        with self._state() as state:
            self._save(state, reload=False)

    def provision(self, project_id: str, stream_max_bytes: int = 1073741824) -> tuple[str, dict]:
        name = self._name(project_id)
        with self._state() as state:
            if project_id not in state["accounts"]:
                state["accounts"][project_id] = {"users": {
                    f"{name}_admin": _hash_password(self._admin_password(project_id))}}
                self._save(state)
        with self._connect(f"{name}_admin", self._admin_password(project_id)) as connection:
            response = connection.request(f"$JS.API.STREAM.INFO.{name}", allow_error=True)
            if response.get("error", {}).get("err_code") == 10059:
                connection.request(f"$JS.API.STREAM.CREATE.{name}", {
                    "name": name, "subjects": [f"{name}.>"], "storage": "file",
                    "retention": "limits", "max_bytes": stream_max_bytes,
                })
            elif response.get("error"):
                raise RuntimeError(f"NATS stream lookup failed: {response['error']}")
        return name, {"url": self.settings.nats_public_url, "account": name,
                      "stream": name, "subject_prefix": f"{name}.", "stream_max_bytes": stream_max_bytes, "tls": True}

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("NATS credentials only support runtime access")
        self._name(project_id)
        with self._state() as state:
            state["accounts"][project_id]["users"][username] = _hash_password(secret)
            self._save(state)
        with self._connect(username, secret):
            pass

    def revoke(self, project_id: str, username: str) -> None:
        self._name(project_id)
        with self._state() as state:
            account = state["accounts"].get(project_id)
            if account and username in account["users"]:
                del account["users"][username]
                self._save(state)

    def delete(self, project_id: str) -> None:
        name = self._name(project_id)
        with self._state() as state:
            if project_id not in state["accounts"]:
                return
            with self._connect(f"{name}_admin", self._admin_password(project_id)) as connection:
                connection.request(f"$JS.API.STREAM.DELETE.{name}")
            del state["accounts"][project_id]
            self._save(state)


if __name__ == "__main__":
    NatsAdapter(get_settings()).initialize()
