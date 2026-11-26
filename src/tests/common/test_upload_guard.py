# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.upload_guard import check_upload, max_request_bytes, upload_problem

PDF = b"%PDF-1.7\n%..."
DOCX = b"PK\x03\x04\x14\x00\x06\x00"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "


def _pe():
    head = bytearray(b"MZ" + b"\x00" * 0x3E)
    head[0x3C:0x40] = (0x80).to_bytes(4, "little")
    return bytes(head) + b"\x00" * (0x80 - len(head)) + b"PE\x00\x00"


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv("IAT_MAX_UPLOAD_MB", raising=False)
    monkeypatch.delenv("IAT_MAX_REQUEST_MB", raising=False)


@pytest.mark.parametrize("filename, content", [
    ("report.pdf", PDF), ("contract.docx", DOCX), ("sales.xlsx", DOCX), ("legacy.xls", OLE),
    ("modern-saved-as.xls", DOCX), ("photo.png", PNG), ("photo.jpg", JPEG), ("renamed.png", JPEG),
    ("photo.webp", WEBP), ("notes.txt", b"hello"), ("data.csv", b"a,b\n1,2"),
    ("utf16.txt", b"\xff\xfeh\x00i\x00"), ("readme.md", b"#!/bin/sh is just text in a .md"),
    ("unknown.xyz", b"anything"), ("empty.pdf", b""), ("names.csv", b"MZ,second\n1,2"),
])
def test_legitimate_files_pass(filename, content):
    assert upload_problem(filename, content) is None


@pytest.mark.parametrize("filename, content, reason", [
    ("invoice.pdf", _pe(), "windows_executable"),
    ("tool.exe", _pe(), "windows_executable"),
    ("data.csv", b"\x7fELF\x02\x01\x01", "elf_executable"),
    ("report.docx", b"\xcf\xfa\xed\xfe\x07\x00", "macho_executable"),
    ("install.sh", b"#!/bin/bash\nrm -rf /", "script"),
    ("noext", b"#!/usr/bin/env python", "script"),
    ("invoice.pdf", b"<html><script>alert(1)</script>", "content_does_not_match_extension"),
    ("contract.docx", PDF, "content_does_not_match_extension"),
    ("photo.png", b"<svg onload=alert(1)>", "content_does_not_match_extension"),
    ("notes.txt", b"abc\x00\x01\x02binary", "binary_content_in_text_file"),
])
def test_disguised_or_executable_files_are_refused(filename, content, reason):
    assert upload_problem(filename, content) == reason


def test_size_limit_defaults_to_50_mb_and_is_configurable(monkeypatch):
    assert upload_problem("a.txt", b"x", size=50 * 1024 * 1024) is None
    assert upload_problem("a.txt", b"x", size=50 * 1024 * 1024 + 1) == "too_large"

    monkeypatch.setenv("IAT_MAX_UPLOAD_MB", "1")
    assert upload_problem("a.txt", b"x", size=2 * 1024 * 1024) == "too_large"

    monkeypatch.setenv("IAT_MAX_UPLOAD_MB", "nonsense")
    assert upload_problem("a.txt", b"x", size=2 * 1024 * 1024) is None


def test_the_request_limit_defaults_to_100_mb(monkeypatch):
    assert max_request_bytes() == 100 * 1024 * 1024
    monkeypatch.setenv("IAT_MAX_REQUEST_MB", "20")
    assert max_request_bytes() == 20 * 1024 * 1024


def test_a_refusal_raises_and_logs_the_reason_without_the_content(caplog):
    with caplog.at_level(logging.WARNING):
        with pytest.raises(IAToolkitException) as info:
            check_upload("invoice.pdf", b"<html>secret-content</html>")

    assert info.value.error_type == IAToolkitException.ErrorType.FILE_FORMAT_ERROR
    assert "event=upload_rejected reason=content_does_not_match_extension extension=pdf" in caplog.text
    assert "secret-content" not in caplog.text


def test_a_large_request_body_is_refused_by_the_app(monkeypatch):
    """MAX_CONTENT_LENGTH, as core sets it, answers 413 before the view reads the body."""
    from flask import Flask, request
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024

    @app.post("/upload")
    def upload():
        return {"size": len(request.get_data())}

    client = app.test_client()
    assert client.post("/upload", data=b"x" * 100).status_code == 200
    assert client.post("/upload", data=b"x" * 2048).status_code == 413
