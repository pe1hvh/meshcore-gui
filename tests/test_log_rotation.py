"""Regression tests: debug and library lines share one rotating log file.

Before 1.26.5 ``config._init_file_logger`` and
``config._init_meshcore_logger`` each attached their own
``RotatingFileHandler`` to the same file.  When one of them rotated, the
other kept writing to the renamed file (``.log.1`` ... ``.log.3``) and
went on writing to it after it was rotated away, so the ``DEBUG`` lines
ended up in a deleted file.  These tests check that both loggers write to
the current log file after several rotations.

Structure:

1. Fixture: an isolated log file with a small rotation size.
2. Tests: one shared handler, both kinds of lines in the current file.
"""

import logging
import os
from pathlib import Path
from typing import Iterator, List

import pytest

from meshcore_gui import config

# ===========================================================================
# 1. Fixture
# ===========================================================================

LOGGER_NAMES = ("meshcore_gui.debug", "meshcore")
"""Loggers that ``config`` attaches handlers to."""


def _reset_loggers() -> None:
    """Remove and close every handler ``config`` may have attached."""
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


@pytest.fixture(name="log_file")
def fixture_log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the log at a temporary file that rotates every 2 kB.

    Args:
        tmp_path: Temporary directory from pytest.
        monkeypatch: Pytest fixture to patch module attributes.

    Yields:
        Path of the current log file.
    """
    _reset_loggers()
    path = tmp_path / "dev_meshcore_gui.log"
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_FILE", path)
    monkeypatch.setattr(config, "LOG_MAX_BYTES", 2048)
    monkeypatch.setattr(config, "LOG_BACKUP_COUNT", 3)
    monkeypatch.setattr(config, "DEBUG", True)
    monkeypatch.setattr(config, "_file_logger", None)
    monkeypatch.setattr(config, "_file_handler", None, raising=False)
    yield path
    _reset_loggers()

# ===========================================================================
# 2. Tests
# ===========================================================================


def _file_handlers() -> List[logging.FileHandler]:
    """Return the file handlers on both loggers.

    Returns:
        Every ``logging.FileHandler`` attached to a logger in
        :data:`LOGGER_NAMES` (a shared handler appears once per logger).
    """
    return [h for name in LOGGER_NAMES for h in logging.getLogger(name).handlers
            if isinstance(h, logging.FileHandler)]


def _write_many(count: int) -> None:
    """Write *count* debug lines and *count* library lines, interleaved.

    Args:
        count: Lines per logger; 100 lines of ~60 bytes rotate a 2 kB
            file several times.
    """
    lib = logging.getLogger("meshcore")
    lib.setLevel(logging.DEBUG)
    for i in range(count):
        config.debug_print(f"debug line {i:04d} " + "x" * 30)
        lib.debug("library line %04d %s", i, "y" * 30)


def test_one_handler_for_both_loggers(log_file: Path) -> None:
    """Both loggers use the very same file handler object.

    Args:
        log_file: Current log file from the fixture.
    """
    config.debug_print("start")
    handlers = _file_handlers()
    assert len(handlers) == 2
    assert handlers[0] is handlers[1]
    assert Path(handlers[0].baseFilename) == log_file


def test_no_handle_to_rotated_file(log_file: Path) -> None:
    """After rotations every file handler writes to the current log file.

    Args:
        log_file: Current log file from the fixture.
    """
    _write_many(100)
    current = os.stat(log_file).st_ino
    for handler in _file_handlers():
        assert os.fstat(handler.stream.fileno()).st_ino == current


def test_last_lines_of_both_loggers_in_current_file(log_file: Path) -> None:
    """The newest debug and library lines end up in the current file.

    Args:
        log_file: Current log file from the fixture.
    """
    _write_many(100)
    config.debug_print("final debug marker")
    logging.getLogger("meshcore").debug("final library marker")
    text = log_file.read_text(encoding="utf-8")
    assert "DEBUG [" in text and "final debug marker" in text
    assert "LIB [meshcore]: final library marker" in text


def test_line_formats_unchanged(log_file: Path) -> None:
    """Debug and library lines keep their pre-1.26.5 layout.

    Args:
        log_file: Current log file from the fixture.
    """
    config.debug_print("hello")
    logging.getLogger("meshcore").debug("world")
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines[0][19:] == "  DEBUG [test_log_rotation]: hello"
    assert lines[1][19:] == "  LIB [meshcore]: world"
