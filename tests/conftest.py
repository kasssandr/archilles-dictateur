import logging

import pytest


@pytest.fixture(autouse=True)
def _isolated_daemon_logging(monkeypatch):
    """Keep tests out of the real daemon log.

    DaemonServer() calls setup_logging(), which attaches a file handler for
    %APPDATA%\\archilles-dictateur\\daemon.log. Without this fixture every test
    that builds a server writes its mock traffic (including lines such as
    "<MagicMock ...> failed") into the log the user reads when debugging.
    """
    import daemon

    logger = logging.getLogger("archilles-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    monkeypatch.setattr(daemon, "setup_logging", lambda: logger)
    yield
