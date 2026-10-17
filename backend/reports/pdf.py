from __future__ import annotations

import re
from io import BytesIO

from fpdf import FPDF


def _latin1_safe(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    return text


def _soft_break(text: str, max_run: int = 80) -> str:
    """Insert spaces into very long unbroken runs so fpdf can wrap."""
    parts: list[str] = []
    for token in text.split(" "):
        if len(token) <= max_run:
            parts.append(token)
            continue
        chunks = [token[i : i + max_run] for i in range(0, len(token), max_run)]
        parts.append(" ".join(chunks))
    return " ".join(parts)


def markdown_to_pdf_bytes(markdown: str) -> bytes:
    """Render audit markdown as a simple structured PDF."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    body_size = 10
    pdf.set_font("Helvetica", size=body_size)

    def write_line(text: str, *, size: int = body_size, bold: bool = False, indent: float = 0) -> None:
        style = "B" if bold else ""
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin + indent)
        usable = max(pdf.epw - indent, 20)
        safe = _soft_break(_latin1_safe(text))
        pdf.multi_cell(usable, max(5, size * 0.55), safe)
        pdf.set_x(pdf.l_margin)

    for raw_line in markdown.splitlines():
        line = _strip_inline_md(raw_line.rstrip())
        if not line.strip():
            pdf.ln(3)
            continue

        if line.startswith("# "):
            pdf.ln(4)
            write_line(line[2:].strip(), size=16, bold=True)
            continue
        if line.startswith("## "):
            pdf.ln(3)
            write_line(line[3:].strip(), size=13, bold=True)
            continue
        if line.startswith("### "):
            pdf.ln(2)
            write_line(line[4:].strip(), size=11, bold=True)
            continue

        indent = 0.0
        content = line
        if content.startswith("  - "):
            indent = 8
            content = "- " + content[4:]
        elif content.startswith("- "):
            indent = 4
            content = "- " + content[2:]

        write_line(content, indent=indent)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
