import logging
from pathlib import Path

from sentinel.utils.logging import setup_file_logging


def test_setup_file_logging_defaults_to_current_working_directory_logs(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    root_logger.handlers.clear()

    try:
        log_path = Path(setup_file_logging())
    finally:
        for handler in root_logger.handlers[:]:
            handler.close()
        root_logger.handlers[:] = original_handlers

    assert log_path.parent == tmp_path / "logs"
    assert log_path.name.startswith("sentinel_")
