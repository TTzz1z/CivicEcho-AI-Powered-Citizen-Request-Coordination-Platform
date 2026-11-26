"""Document parsing for KB uploads.

Supports PDF, Word (.docx), Markdown and plain text. Detects scanned PDFs and
marks OCR status/quality. PDFs that look scanned are flagged with
``ocr_status='required'`` but text extraction still attempts OCR-free path;
this keeps the dependency footprint small (no Tesseract runtime required) while
still recording the OCR signal for admins.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from threading import BoundedSemaphore

logger = logging.getLogger(__name__)
MAX_PARSE_INPUT_BYTES = 20 * 1024 * 1024
MAX_PARSE_TEXT_CHARS = 500_000
MAX_PDF_PAGES = 400
PARSE_TIMEOUT_SECONDS = 15
PARSE_MEMORY_BYTES = 384 * 1024 * 1024
_PARSER_SLOTS = BoundedSemaphore(2)


@dataclass
class ParsedDocument:
    text: str
    file_type: str
    ocr_status: str  # none / required / done / failed
    ocr_quality: float | None  # 0.0 - 1.0
    page_count: int | None
    parser_notes: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.text and self.text.strip())


def parse_bytes(data: bytes, filename: str, mime_type: str | None = None) -> ParsedDocument:
    """Parse uploaded bytes in a replaceable process with a wall-clock limit."""
    filename = filename or ""
    extension = filename.lower().rsplit(".", 1)[-1]
    file_type = {"pdf": "pdf", "doc": "word", "docx": "word", "md": "markdown", "markdown": "markdown"}.get(extension, "text")
    if len(data) > MAX_PARSE_INPUT_BYTES:
        return _budget_failure(file_type, "文件体积超过解析上限")
    if not _PARSER_SLOTS.acquire(blocking=False):
        return _budget_failure(file_type, "文档解析繁忙，请稍后重试")
    try:
        completed = subprocess.run(
            [sys.executable, "-B", __file__, "--parse-worker", filename, mime_type or ""],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PARSE_TIMEOUT_SECONDS,
            check=True,
        )
        return ParsedDocument(**json.loads(completed.stdout))
    except subprocess.TimeoutExpired:
        return _budget_failure(file_type, "文档解析超时")
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError):
        return _budget_failure(file_type, "文档解析失败或超过资源上限")
    finally:
        _PARSER_SLOTS.release()


def _budget_failure(file_type: str, note: str) -> ParsedDocument:
    return ParsedDocument(text="", file_type=file_type, ocr_status="failed",
                          ocr_quality=None, page_count=None, parser_notes=[note])


def _parse_document(data: bytes, filename: str, mime_type: str) -> ParsedDocument:
    name = (filename or "").lower()
    if name.endswith(".pdf") or (mime_type or "").lower() == "application/pdf":
        return _parse_pdf(data)
    if name.endswith(".docx") or (mime_type or "").lower() in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return _parse_docx(data)
    if name.endswith(".doc") or (mime_type or "").lower() == "application/msword":
        # python-docx does not support legacy .doc; flag as failed.
        return ParsedDocument(text="", file_type="word", ocr_status="none",
                              ocr_quality=None, page_count=None,
                              parser_notes=["legacy .doc 不支持，请转换为 .docx 后再上传"])
    if name.endswith((".md", ".markdown")):
        return _parse_markdown(data.decode("utf-8", errors="ignore"))
    if name.endswith((".txt", ".text")) or (mime_type or "").lower().startswith("text/"):
        return ParsedDocument(
            text=data.decode("utf-8", errors="ignore"),
            file_type="text", ocr_status="none", ocr_quality=None,
            page_count=None, parser_notes=[],
        )
    # Fallback: try utf-8 decode
    return ParsedDocument(
        text=data.decode("utf-8", errors="ignore"),
        file_type="text", ocr_status="none", ocr_quality=None,
        page_count=None, parser_notes=["未识别的文件类型，按纯文本处理"],
    )


def _parse_pdf(data: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        logger.warning("pypdf not available: %s", exc)
        return ParsedDocument(text="", file_type="pdf", ocr_status="failed",
                              ocr_quality=None, page_count=None,
                              parser_notes=["pypdf 未安装"])
    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            return _budget_failure("pdf", f"PDF 超过 {MAX_PDF_PAGES} 页的解析上限")
        pages_text: list[str] = []
        text_chars = 0
        non_text_pages = 0
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception as exc:  # extraction can fail per-page
                logger.debug("page extract failed: %s", exc)
                txt = ""
            text_chars += len(txt)
            if text_chars > MAX_PARSE_TEXT_CHARS:
                return _budget_failure("pdf", "PDF 正文超过解析上限")
            pages_text.append(txt)
            # Heuristic: a page with very few extractable chars likely is scanned
            stripped = re.sub(r"\s+", "", txt)
            if len(stripped) < 20:
                non_text_pages += 1
        text = "\f".join(page.strip() for page in pages_text)
        # OCR signal: if >50% of pages have no extractable text, mark as scanned
        if page_count > 0 and non_text_pages / page_count > 0.5:
            ocr_status = "required"
            ocr_quality = round(1.0 - non_text_pages / page_count, 3)
            notes = [f"检测到 {non_text_pages}/{page_count} 页疑似扫描内容，建议补充 OCR 文本或上传文本版本"]
        else:
            ocr_status = "none"
            ocr_quality = None
            notes = []
        return ParsedDocument(
            text=text, file_type="pdf", ocr_status=ocr_status,
            ocr_quality=ocr_quality, page_count=page_count, parser_notes=notes,
        )
    except Exception as exc:
        logger.warning("PDF parse failed: %s", exc)
        return ParsedDocument(text="", file_type="pdf", ocr_status="failed",
                              ocr_quality=None, page_count=None,
                              parser_notes=[f"PDF 解析失败：{exc}"])


def _parse_docx(data: bytes) -> ParsedDocument:
    try:
        from docx import Document
    except ImportError as exc:
        logger.warning("python-docx not available: %s", exc)
        return ParsedDocument(text="", file_type="word", ocr_status="failed",
                              ocr_quality=None, page_count=None,
                              parser_notes=["python-docx 未安装"])
    try:
        doc = Document(io.BytesIO(data))
        parts: list[str] = []
        text_chars = 0
        from docx.text.paragraph import Paragraph

        for block in doc.iter_inner_content():
            if isinstance(block, Paragraph):
                line = block.text.strip()
                if line:
                    prefix = "# " if block.style and block.style.name.startswith("Heading") else ""
                    parts.append(prefix + line)
                    text_chars += len(prefix) + len(line)
            else:
                for row in block.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        parts.append(row_text)
                        text_chars += len(row_text)
                    if text_chars > MAX_PARSE_TEXT_CHARS:
                        return _budget_failure("word", "Word 正文超过解析上限")
            if text_chars > MAX_PARSE_TEXT_CHARS:
                return _budget_failure("word", "Word 正文超过解析上限")
        return ParsedDocument(
            text="\n\n".join(parts), file_type="word", ocr_status="none",
            ocr_quality=None, page_count=None, parser_notes=[],
        )
    except Exception as exc:
        logger.warning("DOCX parse failed: %s", exc)
        return ParsedDocument(text="", file_type="word", ocr_status="failed",
                              ocr_quality=None, page_count=None,
                              parser_notes=[f"Word 解析失败：{exc}"])


def _parse_markdown(text: str) -> ParsedDocument:
    try:
        import markdown as md  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore
        html = md.markdown(text, extensions=["tables"])
        soup = BeautifulSoup(html, "html.parser")
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            heading.string = "#" * int(heading.name[1]) + " " + heading.get_text(" ", strip=True)
        plain = soup.get_text(separator="\n")
        return ParsedDocument(
            text=plain.strip(), file_type="markdown", ocr_status="none",
            ocr_quality=None, page_count=None, parser_notes=[],
        )
    except ImportError:
        # Without markdown lib, just strip basic syntax
        text = re.sub(r"^[#>\-*]+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"`{1,3}", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        return ParsedDocument(
            text=text.strip(), file_type="markdown", ocr_status="none",
            ocr_quality=None, page_count=None,
            parser_notes=["markdown 库未安装，已按基础规则解析"],
        )


def _parse_worker(filename: str, mime_type: str) -> None:
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (PARSE_MEMORY_BYTES, PARSE_MEMORY_BYTES))
    data = sys.stdin.buffer.read(MAX_PARSE_INPUT_BYTES + 1)
    if len(data) > MAX_PARSE_INPUT_BYTES:
        raise SystemExit("document input exceeds the limit")
    result = _parse_document(data, filename, mime_type)
    if len(result.text) > MAX_PARSE_TEXT_CHARS:
        result = _budget_failure(result.file_type, "文档正文超过解析上限")
    sys.stdout.buffer.write(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8"))


# --- Text utilities used by KB service ---

CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_]*|\d+")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？；\n])")


def extract_keywords(text: str, max_keywords: int = 20) -> list[str]:
    """Extract a simple keyword list from text (Chinese-aware)."""
    if not text:
        return []
    # Take CJK runs and ASCII words
    raw = TOKEN_PATTERN.findall(text)
    # Filter stopwords & short tokens
    stop = {"的", "了", "和", "是", "在", "与", "或", "及", "以及", "对", "为", "于", "由", "从", "向", "至"}
    seen: set[str] = set()
    result: list[str] = []
    for token in raw:
        token = token.strip()
        if not token or token in stop or len(token) < 2:
            continue
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= max_keywords:
            break
    return result


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--parse-worker":
    _parse_worker(sys.argv[2], sys.argv[3])
