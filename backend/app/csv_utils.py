"""UTF-8 BOM streaming CSV helpers with formula injection neutralization."""
import csv
import io
from collections.abc import Iterable, Iterator


_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_csv_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    stripped = text.lstrip(" \t\r\n")
    if text.startswith(_DANGEROUS_PREFIXES) or stripped.startswith(_DANGEROUS_PREFIXES):
        return "'" + text
    return text


def iter_csv_chunks(
    headers: list[str],
    rows: Iterable[list[object]],
    *,
    chunk_size: int = 200,
) -> Iterator[bytes]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([neutralize_csv_cell(header) for header in headers])
    yield b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
    buffer.seek(0)
    buffer.truncate(0)

    pending = 0
    for row in rows:
        writer.writerow([neutralize_csv_cell(cell) for cell in row])
        pending += 1
        if pending >= chunk_size:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
            pending = 0

    if pending > 0:
        yield buffer.getvalue().encode("utf-8")
