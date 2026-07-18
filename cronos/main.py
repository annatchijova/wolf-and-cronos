"""
CRONOS — entry point.
Validates credentials, initializes the store, starts the Bolt Socket Mode handler.
"""

import asyncio
import logging
import signal

from config import Config
from cronos.store import TraceStore
from slack.bot import create_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("cronos.main")


async def main() -> None:
    config = Config()
    config.validate_credentials()

    log.info("CRONOS starting — DB: %s", config.CRONOS_DB_PATH)
    store = TraceStore(config.CRONOS_DB_PATH)

    _, handler = create_app(config, store)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _signal_handler(sig: signal.Signals) -> None:
        log.info("CRONOS received %s — initiating graceful shutdown", sig.name)
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler, sig)

    log.info("CRONOS ready — Socket Mode connected")

    # Run the handler until a stop signal arrives
    handler_task = asyncio.create_task(handler.start_async())
    await stop.wait()

    log.info("CRONOS shutting down…")
    handler_task.cancel()
    try:
        await handler_task
    except (asyncio.CancelledError, Exception):
        pass
    log.info("CRONOS stopped")


if __name__ == "__main__":
    asyncio.run(main())
