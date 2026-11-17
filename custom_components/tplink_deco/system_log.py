"""Bounded TP-Link Deco system-log decoding and severity selection."""

from enum import IntEnum
import gzip
import io
from pathlib import PurePosixPath
import tarfile
import zlib

from .exceptions import UnexpectedApiException

MAX_SYSTEM_LOG_BYTES = 8 * 1024 * 1024
MAX_SYSTEM_LOG_ARCHIVE_MEMBERS = 1024


def _decode_utf8_log(body: bytes) -> str:
    """Decode log text strictly and reject unexpected binary payloads."""
    if b"\x00" in body:
        raise UnexpectedApiException("System log snapshot contains binary data")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise UnexpectedApiException(
            "System log snapshot encoding is unsupported"
        ) from None


def _decompress_gzip_log(body: bytes) -> bytes:
    """Inflate at most the permitted output size, including nested tar data."""
    invalid_gzip = False
    expanded = b""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body), mode="rb") as compressed:
            expanded = compressed.read(MAX_SYSTEM_LOG_BYTES + 1)
    except (EOFError, OSError, zlib.error):
        invalid_gzip = True
    if invalid_gzip:
        raise UnexpectedApiException("System log gzip snapshot is malformed")
    if len(expanded) > MAX_SYSTEM_LOG_BYTES:
        raise UnexpectedApiException("System log expanded snapshot exceeds size limit")
    return expanded


def _read_tar_log(body: bytes) -> bytes | None:
    """Choose syslog.log or the first regular file without disk extraction."""
    try:
        archive = tarfile.open(fileobj=io.BytesIO(body), mode="r:")
    except tarfile.ReadError:
        if body[257:262] == b"ustar":
            raise UnexpectedApiException("System log tar snapshot is malformed") from None
        return None
    except (tarfile.TarError, OSError, EOFError, ValueError):
        raise UnexpectedApiException("System log tar snapshot is malformed") from None

    try:
        with archive:
            first_regular: tarfile.TarInfo | None = None
            selected: tarfile.TarInfo | None = None
            for index, member in enumerate(archive):
                if index >= MAX_SYSTEM_LOG_ARCHIVE_MEMBERS:
                    raise UnexpectedApiException(
                        "System log archive contains too many members"
                    )
                if not member.isfile():
                    continue
                if member.size < 0 or member.size > MAX_SYSTEM_LOG_BYTES:
                    raise UnexpectedApiException(
                        "System log archive member exceeds size limit"
                    )
                if first_regular is None:
                    first_regular = member
                if PurePosixPath(member.name).name == "syslog.log":
                    selected = member
                    break

            selected = selected or first_regular
            if selected is None:
                return b""
            extracted = archive.extractfile(selected)
            if extracted is None:
                raise UnexpectedApiException("System log archive entry is unreadable")
            with extracted:
                contents = extracted.read(MAX_SYSTEM_LOG_BYTES + 1)
            if len(contents) != selected.size:
                raise UnexpectedApiException("System log archive entry is incomplete")
            return contents
    except (tarfile.TarError, OSError, EOFError, ValueError):
        raise UnexpectedApiException("System log tar snapshot is malformed") from None


def decode_system_log(body: bytes) -> str:
    """Decode plain, gzip, tar and gzip-tar snapshots with strict safety limits."""
    if len(body) > MAX_SYSTEM_LOG_BYTES:
        raise UnexpectedApiException("System log snapshot exceeds size limit")
    if body.startswith(b"\x1f\x8b"):
        body = _decompress_gzip_log(body)
    tar_log = _read_tar_log(body)
    return _decode_utf8_log(body if tar_log is None else tar_log)




class SystemLogLevel(IntEnum):
    """Router log severity threshold, where ALL disables severity filtering."""

    ALERT = 1
    CRITICAL = 2
    ERROR = 3
    WARNING = 4
    NOTICE = 5
    INFO = 6
    DEBUG = 7
    ALL = 8
