"""
ocr_extractor.py
-----------------
Extracts raw text from a medical bill image or PDF using Tesseract OCR,
with preprocessing (grayscale, autocontrast, sharpen) to improve accuracy.
"""

import io
import os
from typing import Union

import pytesseract
from PIL import Image, ImageOps, ImageFilter


class OCRExtractor:
    def __init__(self, tesseract_config: str = "--oem 3 --psm 6"):
        self.tesseract_config = tesseract_config

    @staticmethod
    def _preprocess(img: Image.Image) -> Image.Image:
        img = img.convert("L")
        img = ImageOps.autocontrast(img)
        img = img.filter(ImageFilter.SHARPEN)
        return img

    def extract_from_image(self, image_path_or_bytes: Union[str, bytes]) -> str:
        if isinstance(image_path_or_bytes, bytes):
            img = Image.open(io.BytesIO(image_path_or_bytes))
        else:
            img = Image.open(image_path_or_bytes)
        img = self._preprocess(img)
        return pytesseract.image_to_string(img, config=self.tesseract_config)

    def extract_from_pdf(self, pdf_path: str, dpi: int = 300) -> str:
        from pdf2image import convert_from_path
        pages = convert_from_path(pdf_path, dpi=dpi)
        full_text = []
        for i, page_img in enumerate(pages):
            page_img = self._preprocess(page_img)
            text = pytesseract.image_to_string(page_img, config=self.tesseract_config)
            full_text.append(f"--- Page {i+1} ---\n{text}")
        return "\n".join(full_text)

    def extract(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return self.extract_from_pdf(file_path)
        elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            return self.extract_from_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
