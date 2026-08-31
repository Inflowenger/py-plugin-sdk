# NATS connection from base64-encoded decorated credentials. Mirrors nats/natsBox.go.
import base64
import json
import tempfile

import nats
from nats.aio.client import Client as NatsConnection

NATS_DEFAULT_INBOX = "_INBOX"


class NatsBox:
    def __init__(self, cred_b64: str, url: str):
        self.cred = cred_b64
        self.url = url
        self.inbox = NATS_DEFAULT_INBOX
        self.con: NatsConnection | None = None
        self._creds_path: str | None = None

    @classmethod
    async def create(cls, cred_b64: str, url: str) -> "NatsBox":
        """Decode credentials, honor an optional custom inbox prefix, and connect."""
        n = cls(cred_b64, url)
        n._extract_token()
        await n.connect()
        return n

    def _extract_token(self) -> None:
        # INFRA_CRED is the decorated .creds file, base64-encoded.
        self.cred = base64.b64decode(self.cred).decode("utf-8")

        # Access-hardening (internal): when many plugins share one account, the
        # user JWT may carry a custom inbox prefix tag scoping its private reply
        # inboxes. Best-effort; falls back to the default inbox otherwise.
        try:
            inbox = _custom_inbox_from_creds(self.cred)
            if inbox:
                self.inbox = inbox
        except Exception:
            pass  # optional

    async def connect(self) -> None:
        url = self.url if "://" in self.url else f"nats://{self.url}"

        # nats-py reads credentials from a file path; write the decoded .creds
        # blob to a temp file and keep it for the life of the process (reconnects
        # re-read it).
        if self._creds_path is None:
            f = tempfile.NamedTemporaryFile(mode="w", suffix=".creds", delete=False)
            f.write(self.cred)
            f.close()
            self._creds_path = f.name

        async def reconnected_cb():
            print(f"Reconnected to NATS server: {self.con.connected_url}")

        async def disconnected_cb():
            print("Disconnected from NATS server")

        async def error_cb(err):
            print(f"NATS error: {err}")

        async def closed_cb():
            print("Connection to NATS server closed")

        self.con = await nats.connect(
            servers=url,
            user_credentials=self._creds_path,
            inbox_prefix=self.inbox.encode(),
            allow_reconnect=True,
            max_reconnect_attempts=-1,
            ping_interval=30,
            reconnected_cb=reconnected_cb,
            disconnected_cb=disconnected_cb,
            error_cb=error_cb,
            closed_cb=closed_cb,
        )

    @property
    def connection(self) -> NatsConnection | None:
        return self.con

    def get_connection(self) -> NatsConnection | None:
        return self.con


def _custom_inbox_from_creds(creds: str) -> str | None:
    """Pull a `_INBOX*` tag out of the user JWT inside a decorated .creds blob."""
    marker_begin = "-----BEGIN NATS USER JWT-----"
    marker_end = "-----END NATS USER JWT-----"
    if marker_begin not in creds or marker_end not in creds:
        return None
    jwt = creds.split(marker_begin, 1)[1].split(marker_end, 1)[0].strip()
    parts = jwt.split(".")
    if len(parts) < 2:
        return None
    payload_raw = parts[1]
    payload_raw += "=" * (-len(payload_raw) % 4)  # pad base64url
    payload = json.loads(base64.urlsafe_b64decode(payload_raw).decode("utf-8"))
    tags = (payload.get("nats") or {}).get("tags") or []
    for t in tags:
        if t.startswith(NATS_DEFAULT_INBOX):
            return t
    return None
