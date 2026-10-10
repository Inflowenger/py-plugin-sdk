"""In-memory NATS doubles so the SDK can be tested without a broker."""
from __future__ import annotations

import pytest
from nats.errors import NoRespondersError

from inflow_plugin_sdk import Plugin


class MockMsg:
    def __init__(self, data: bytes = b"", headers=None, subject: str = ""):
        self.data = data
        self.headers = headers
        self.subject = subject
        self.responses: list[bytes] = []

    async def respond(self, data: bytes) -> None:
        self.responses.append(data)


class MockConn:
    def __init__(self):
        self.subs: dict[str, object] = {}
        self.reply = b"REPLY"
        self.raise_no_responders = False
        self.requests: list[tuple[str, bytes]] = []

    async def subscribe(self, subject, cb=None):
        self.subs[subject] = cb

    async def request(self, subject, data, timeout=None):
        self.requests.append((subject, data))
        if self.raise_no_responders:
            raise NoRespondersError()
        return MockMsg(data=self.reply)


class MockInfra:
    def __init__(self, conn: MockConn):
        self._conn = conn

    def get_connection(self):
        return self._conn


@pytest.fixture
def conn() -> MockConn:
    return MockConn()


@pytest.fixture
def plugin(conn: MockConn) -> Plugin:
    p = Plugin()
    p.plugin_id = "PID"
    p.infra_conn = MockInfra(conn)
    return p


class RecordingPlugin(Plugin):
    """A plugin whose `send` records commands instead of publishing them, so a
    test can see what a handler reported (and that a stopped handler reported
    nothing)."""

    def __init__(self, plugin_id: str = "PID"):
        super().__init__()
        self.plugin_id = plugin_id
        self.sent: list[tuple[str, bytes]] = []

    async def send(self, subject: str, data: bytes):
        self.sent.append((subject, data))
        return MockMsg(data=b"OK"), None

    def job_ids_seen(self) -> list[str]:
        """The jobId segment of every command sent, in order."""
        return [s.split(".")[3] for s, _ in self.sent]


@pytest.fixture
def rec() -> RecordingPlugin:
    return RecordingPlugin()
