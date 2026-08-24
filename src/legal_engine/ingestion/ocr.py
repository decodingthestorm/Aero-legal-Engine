"""OCR pipeline for scanned PDF dockets.

``OCRPipeline`` is a Protocol; ``TesseractOCRPipeline`` wraps
`pytesseract` + `pdf2image` (rasterizes each page, then runs Tesseract on
it). Both are optional, system-dependent installs — pdf2image needs the
poppler binaries, pytesseract needs the tesseract binary — neither of which
is available in this environment, so the import is deferred to __init__
and this class isn't exercised by the test suite here.
"""

from __future__ import annotations

from typing import Protocol


class OCRPipeline(Protocol):
    def extract_text(self, pdf_bytes: bytes) -> str: ...


class TesseractOCRPipeline:
    def __init__(self, dpi: int = 300) -> None:
        try:
            import pdf2image  # noqa: F401
            import pytesseract  # noqa: F401
        except Exception as exc:
            raise ImportError(
                "TesseractOCRPipeline requires: pip install pytesseract pdf2image "
                "(plus the Tesseract OCR and poppler system binaries) "
                f"(underlying error: {exc.__class__.__name__}: {exc})"
            ) from exc
        self._dpi = dpi

    def extract_text(self, pdf_bytes: bytes) -> str:
        import pytesseract
        from pdf2image import convert_from_bytes

        pages = convert_from_bytes(pdf_bytes, dpi=self._dpi)
        return "\n\n".join(pytesseract.image_to_string(page) for page in pages)
