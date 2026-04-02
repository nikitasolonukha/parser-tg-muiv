from __future__ import annotations


def _read_header(handle, size):
    pos = handle.tell()
    try:
        return handle.read(size)
    finally:
        handle.seek(pos)


def _test_jpeg(header):
    return header.startswith(b"\xFF\xD8")


def _test_png(header):
    return header.startswith(b"\x89PNG\r\n\x1a\n")


def _test_gif(header):
    return header.startswith((b"GIF87a", b"GIF89a"))


def _test_bmp(header):
    return header.startswith(b"BM")


def _test_webp(header):
    return header.startswith(b"RIFF") and header[8:12] == b"WEBP"


_TESTS = [
    ("jpeg", _test_jpeg),
    ("png", _test_png),
    ("gif", _test_gif),
    ("bmp", _test_bmp),
    ("webp", _test_webp),
]


def what(file, header=None):
    if header is None:
        if hasattr(file, "read"):
            header = _read_header(file, 32)
        else:
            with open(file, "rb") as handle:
                header = handle.read(32)
    for name, tester in _TESTS:
        if tester(header):
            return name
    return None
