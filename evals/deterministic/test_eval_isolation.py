"""Offline collection and Python children cannot read user config or call APIs."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


def test_config_was_isolated_before_import():
    from evals.helpers import HAS_KEY
    from waku.config import DOTENV_PATH, Settings

    settings = Settings()
    assert DOTENV_PATH == ""
    assert settings.api_key == ""
    assert settings.home.is_relative_to(Path(os.environ["WAKU_EVAL_ROOT"]))
    assert not HAS_KEY


def test_external_dns_and_connections_are_blocked():
    with pytest.raises(OSError, match="Offline eval"):
        socket.getaddrinfo("example.com", 443)
    with socket.socket() as sock, pytest.raises(OSError, match="Offline eval"):
        sock.connect(("192.0.2.1", 443))
    with socket.socket(type=socket.SOCK_DGRAM) as sock, pytest.raises(OSError, match="Offline eval"):
        sock.sendto(b"synthetic", ("192.0.2.1", 443))


def test_children_inherit_guards_before_config_import():
    code = """
from waku.config import DOTENV_PATH, Settings
import socket
assert DOTENV_PATH == ''
assert Settings().api_key == ''
try:
    socket.getaddrinfo('example.com', 443)
except OSError as exc:
    assert 'Offline eval' in str(exc)
else:
    raise AssertionError('network guard missing')
"""
    child = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert child.returncode == 0, child.stderr


def test_dotenv_outside_scratch_is_rejected_before_reading():
    from dotenv import load_dotenv

    from evals.isolation import ROOT

    with pytest.raises(RuntimeError, match="outside eval scratch"):
        load_dotenv(ROOT / "synthetic-do-not-read.env")
