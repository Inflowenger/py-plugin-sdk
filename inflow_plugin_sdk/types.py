# Job command names — the <CMD> segment of inflow.cpu.<PLUGIN_ID>.<JOB_ID>.<CMD>.
# Mirrors sdkv1/types.go.
from enum import StrEnum


class Command(StrEnum):
    PROGRESS = "progress"
    CONTEXT_CURRENT = "context/current"
    CONTEXT_PATH = "context/path"
    COMMIT = "commit"
    # next_tags — fire only the outbound branch(es) whose tags are named.
    NEXT_TAGS = "next_tags"
    # request/svc — a plugin-originated call to a downstream service.
    REQUEST = "request/svc"
