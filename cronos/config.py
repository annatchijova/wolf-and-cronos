"""
CRONOS — environment configuration.
validate_credentials() is separated from __init__ so tests can
instantiate Config() without real Slack tokens.
"""

import logging
import os
from dataclasses import dataclass, field

_log = logging.getLogger("cronos.config")


@dataclass
class Config:
    SLACK_BOT_TOKEN: str     = ""
    SLACK_APP_TOKEN: str     = ""
    SLACK_SIGNING_SECRET: str = ""
    CRONOS_DB_PATH: str      = "cronos.db"
    LOG_LEVEL: str           = "INFO"
    # Comma-separated channel names or IDs where the demo agent listens
    WATCH_CHANNELS: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.SLACK_BOT_TOKEN      = os.environ.get("SLACK_BOT_TOKEN",      "")
        self.SLACK_APP_TOKEN      = os.environ.get("SLACK_APP_TOKEN",       "")
        self.SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET",  "")
        self.CRONOS_DB_PATH       = os.environ.get("CRONOS_DB_PATH",        "cronos.db")
        self.LOG_LEVEL            = os.environ.get("LOG_LEVEL",             "INFO")
        raw = os.environ.get("CRONOS_WATCH_CHANNELS", "")
        parsed = [c.strip().lstrip("#") for c in raw.split(",") if c.strip()]
        # Slack channel IDs start with C or G followed by uppercase alphanumerics.
        # Names (e.g. "general") will never match the event channel ID from Slack.
        # Warn loudly so operators don't spend time debugging a silent no-op filter.
        for ch in parsed:
            if ch and not (len(ch) >= 9 and ch[0] in "CGD" and ch.isalnum()):
                _log.warning(
                    "CRONOS_WATCH_CHANNELS: %r looks like a channel name, not an ID. "
                    "Slack events carry channel IDs (e.g. C0123456789). "
                    "This filter will never match — use the channel ID instead.",
                    ch,
                )
        self.WATCH_CHANNELS = parsed

    def validate_credentials(self) -> None:
        """
        Validate Slack token formats before the Bolt app starts.
        Raises ValueError with a descriptive message on the first failure.
        """
        if not self.SLACK_BOT_TOKEN.startswith("xoxb-"):
            raise ValueError(
                "SLACK_BOT_TOKEN must start with 'xoxb-'. "
                "Got: " + repr(self.SLACK_BOT_TOKEN[:12] + "…")
            )
        if not self.SLACK_APP_TOKEN.startswith("xapp-"):
            raise ValueError(
                "SLACK_APP_TOKEN must start with 'xapp-'. "
                "Got: " + repr(self.SLACK_APP_TOKEN[:12] + "…")
            )
        if not self.SLACK_SIGNING_SECRET:
            raise ValueError("SLACK_SIGNING_SECRET is required")
