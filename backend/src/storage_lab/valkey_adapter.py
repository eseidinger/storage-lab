"""Valkey namespace and ACL administration over the small RESP subset we use."""

import socket
import ssl

from .settings import Settings


class ValkeyError(RuntimeError):
    pass


class ValkeyConnection:
    def __init__(self, host: str, port: int = 6379, *, tls: bool = False, ca_file: str | None = None):
        raw = socket.create_connection((host, port), timeout=10)
        self.socket = ssl.create_default_context(cafile=ca_file).wrap_socket(raw, server_hostname="localhost") if tls else raw
        self.stream = self.socket.makefile("rb")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()
        self.socket.close()

    def command(self, *parts: str):
        encoded = [part.encode() for part in parts]
        self.socket.sendall(f"*{len(encoded)}\r\n".encode() + b"".join(
            f"${len(item)}\r\n".encode() + item + b"\r\n" for item in encoded
        ))
        return self._read()

    def _read(self):
        prefix = self.stream.read(1)
        line = self.stream.readline().rstrip(b"\r\n")
        if prefix == b"-":
            raise ValkeyError(line.decode())
        if prefix == b"+":
            return line.decode()
        if prefix == b":":
            return int(line)
        if prefix == b"$":
            length = int(line)
            return None if length < 0 else self.stream.read(length + 2)[:-2]
        if prefix == b"*":
            return [self._read() for _ in range(int(line))]
        raise ValkeyError("Invalid Valkey response")


class ValkeyAdapter:
    COMMANDS = ("+ping", "+get", "+mget", "+set", "+mset", "+del", "+unlink",
                "+exists", "+expire", "+pexpire", "+ttl", "+pttl", "+incr",
                "+incrby", "+decr", "+decrby")

    def __init__(self, settings: Settings):
        if not settings.valkey_admin_host or not settings.valkey_admin_password:
            raise RuntimeError("Valkey administration is not configured")
        self.settings = settings

    def _connect(self) -> ValkeyConnection:
        connection = ValkeyConnection(self.settings.valkey_admin_host)
        try:
            connection.command("AUTH", "admin", self.settings.valkey_admin_password)
        except Exception:
            connection.socket.close()
            raise
        return connection

    @staticmethod
    def _prefix(project_id: str) -> str:
        return f"sl_{project_id}:"

    def provision(self, project_id: str) -> tuple[str, dict]:
        with self._connect() as connection:
            connection.command("PING")
        prefix = self._prefix(project_id)
        return prefix, {"host": self.settings.valkey_public_host, "port": self.settings.valkey_public_port,
                        "tls": True, "key_prefix": prefix}

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("Valkey credentials only support runtime access")
        with self._connect() as connection:
            connection.command("ACL", "SETUSER", username, "reset", "on", f">{secret}",
                               f"~{self._prefix(project_id)}*", *self.COMMANDS)
            connection.command("ACL", "SAVE")
            user = connection.command("ACL", "GETUSER", username)
            if not user:
                raise ValkeyError("Valkey ACL user was not created")

    def revoke(self, project_id: str, username: str) -> None:
        with self._connect() as connection:
            connection.command("ACL", "DELUSER", username)
            connection.command("ACL", "SAVE")

    def delete(self, project_id: str) -> None:
        prefix = self._prefix(project_id)
        with self._connect() as connection:
            cursor = b"0"
            while True:
                cursor, keys = connection.command("SCAN", cursor.decode(), "MATCH", f"{prefix}*", "COUNT", "1000")
                if keys:
                    connection.command("UNLINK", *(key.decode() for key in keys))
                if cursor == b"0":
                    break
