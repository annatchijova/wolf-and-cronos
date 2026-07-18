import os
import logging
from fractions import Fraction


class Config:
    """
    CORVUS runtime configuration.
    All values sourced from environment variables with sensible defaults.
    """

    # --- Verdict thresholds (class-level constants — never override) ---
    WATCH_THRESHOLD: Fraction = Fraction(1, 5)     # 0.20
    ALERT_THRESHOLD: Fraction = Fraction(9, 20)    # 0.45
    CRITICAL_THRESHOLD: Fraction = Fraction(3, 4)  # 0.75

    def __init__(self) -> None:
        # --- Storage ---
        self.CORVUS_DB_PATH: str = os.environ.get(
            "CORVUS_DB_PATH",
            os.path.join(os.path.expanduser("~"), ".corvus", "memory.db"),
        )

        # Where CRITICAL evidence bundles are sealed and written.
        self.CORVUS_BUNDLE_DIR: str = os.environ.get(
            "CORVUS_BUNDLE_DIR",
            os.path.join(os.path.expanduser("~"), ".corvus", "bundles"),
        )

        # --- Analysis tuning ---
        self.CORROBORATION_THRESHOLD: int = int(
            os.environ.get("CORROBORATION_THRESHOLD", "2")
        )

        # --- Logging ---
        self.LOG_LEVEL: int = getattr(
            logging,
            os.environ.get("LOG_LEVEL", "INFO").upper(),
            logging.INFO,
        )
