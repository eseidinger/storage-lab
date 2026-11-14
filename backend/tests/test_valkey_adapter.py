from storage_lab.settings import Settings
from storage_lab.valkey_adapter import ValkeyAdapter


class FakeConnection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def command(self, *parts):
        self.calls.append(parts)
        if parts[:2] == ("ACL", "GETUSER"):
            return ["flags", ["on"]]
        if parts[0] == "SCAN":
            return [b"0", []]
        return "OK"


def test_valkey_acl_is_reset_and_scoped(monkeypatch):
    adapter = ValkeyAdapter(Settings(valkey_admin_host="valkey", valkey_admin_password="admin-secret"))
    connection = FakeConnection()
    monkeypatch.setattr(adapter, "_connect", lambda: connection)
    project = "a" * 32
    adapter.issue(project, "sl_credential", "workload-secret")
    acl = connection.calls[0]
    assert acl[:5] == ("ACL", "SETUSER", "sl_credential", "reset", "on")
    assert f"~sl_{project}:*" in acl
    assert "+@all" not in acl
    assert "+eval" not in acl
    assert connection.calls[1] == ("ACL", "SAVE")
