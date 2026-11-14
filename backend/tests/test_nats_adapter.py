import json

from storage_lab.nats_adapter import NatsAdapter
from storage_lab.settings import Settings


def test_nats_project_account_and_credential_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr("storage_lab.nats_adapter._hash_password", lambda value: "$2a$" + value)
    calls = []

    class Connection:
        server_id = "server-id"

        def __init__(self, username, password):
            calls.append(("connect", username, password))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def request(self, subject, body=None, **kwargs):
            calls.append(("request", subject, body))
            if subject.endswith(".INFO.sl_" + "a" * 32):
                return {"error": {"err_code": 10059}}
            return {"success": True}

    adapter = NatsAdapter(Settings(nats_config_dir=str(tmp_path), nats_sys_password="system-secret",
                                   nats_tls_ca="/certs/postgres.crt"))
    monkeypatch.setattr(adapter, "_connect", lambda username, password: Connection(username, password))
    adapter.initialize()
    project = "a" * 32
    name, endpoint = adapter.provision(project, stream_max_bytes=2097152)
    assert name == f"sl_{project}"
    assert endpoint["subject_prefix"] == f"sl_{project}."
    assert endpoint["stream_max_bytes"] == 2097152
    assert any(call[1] == f"$JS.API.STREAM.CREATE.{name}" for call in calls if call[0] == "request")
    assert next(call for call in calls if call[0] == "request" and call[1] == f"$JS.API.STREAM.CREATE.{name}")[2]["max_bytes"] == 2097152
    adapter.issue(project, "sl_workload", "workload-secret")
    config = (tmp_path / "nats.conf").read_text()
    assert "sl_workload" in config
    assert "workload-secret" in json.loads((tmp_path / "state.json").read_text())["accounts"][project]["users"]["sl_workload"]
    adapter.revoke(project, "sl_workload")
    assert "sl_workload" not in (tmp_path / "nats.conf").read_text()
    adapter.delete(project)
    assert project not in json.loads((tmp_path / "state.json").read_text())["accounts"]
    assert any(call[1] == f"$JS.API.STREAM.DELETE.{name}" for call in calls if call[0] == "request")
