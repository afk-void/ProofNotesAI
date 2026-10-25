"""Fully on-device file extraction; OCR via installed local Tesseract only."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import os
import shutil
import subprocess

import fitz
from docx import Document
from pptx import Presentation
from PIL import Image, ImageOps, UnidentifiedImageError
import zipfile

from .core import readable_text

SUPPORTED = {'.pdf', '.docx', '.pptx', '.txt', '.md', '.png', '.jpg', '.jpeg', '.webp'}
MAX_FILE_BYTES = 18 * 1024 * 1024
MAX_PAGES = 100
MAX_OCR_PAGES = 18
MAX_IMAGE_PIXELS = 20_000_000


def validate_upload(data: bytes, name: str) -> str:
    """Cheap checks before handing a bounded upload to a document parser."""
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED or len(name) > 180 or any(ord(c) < 32 for c in name):
        raise ValueError('Unsupported or invalid filename. Use PDF, DOCX, PPTX, TXT, MD or an image.')
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError('File is empty or exceeds 18 MB.')
    if ext == '.pdf':
        if not data[:1024].lstrip(b'\xef\xbb\xbf\x00\t\r\n ').startswith(b'%PDF-'):
            raise ValueError('This file is not a valid PDF.')
    elif ext in {'.png', '.jpg', '.jpeg', '.webp'}:
        try:
            with Image.open(BytesIO(data)) as im:
                expected = {'png':'PNG','jpg':'JPEG','jpeg':'JPEG','webp':'WEBP'}[ext[1:]]
                if im.format != expected or im.width * im.height > MAX_IMAGE_PIXELS:
                    raise ValueError('Invalid image format or over 20 megapixels.')
                im.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('Invalid or unsafe image.') from exc
    elif ext in {'.pptx', '.docx'}:
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                info = z.infolist()
                if len(info) > 5000 or sum(x.file_size for x in info) > 90_000_000:
                    raise ValueError('Office document exceeds safe extraction limits.')
                if any(x.file_size > 30_000_000 for x in info):
                    raise ValueError('Office document has an oversized component.')
                prefix = 'word/' if ext == '.docx' else 'ppt/'
                if not '[Content_Types].xml' in z.namelist() or not any(n.startswith(prefix) for n in z.namelist()):
                    raise ValueError('Invalid Office document structure.')
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError('Invalid Office document.') from exc
    elif b'\x00' in data[:65536]:
        raise ValueError('Text file contains binary data.')
    return ext


@dataclass
class Page:
    number: int
    text: str
    ocr: bool = False


def _ocr_image(raw: bytes) -> str:
    if os.getenv('ENABLE_OCR', 'true').lower() != 'true':
        raise ValueError('Image-only page requires local OCR. Enable OCR in .env.')
    exe = shutil.which('tesseract')
    if not exe:
        raise ValueError('Local OCR is missing. Install Tesseract (brew install tesseract / winget install UB-Mannheim.TesseractOCR).')
    with Image.open(BytesIO(raw)) as image:
        img = ImageOps.exif_transpose(image).convert('RGB')
        img.thumbnail((2100, 2700))
        io = BytesIO()
        img.save(io, format='PNG')
    proc = subprocess.run([exe, 'stdin', 'stdout', '-l', 'eng', '--psm', '3'],
                          input=io.getvalue(), capture_output=True, timeout=90, check=False)
    if proc.returncode:
        raise ValueError('Local OCR could not read the image. Try a clearer image or searchable PDF.')
    text = proc.stdout.decode('utf-8', errors='replace').strip()
    if len(text) < 8:
        raise ValueError('Local OCR found too little readable text. Handwriting and formulas may need manual transcription.')
    return text


def extract_pages(path: Path) -> list[Page]:
    suffix = path.suffix.lower()
    pages = []
    if suffix == '.pdf':
        with fitz.open(path) as pdf:
            if len(pdf) > MAX_PAGES:
                raise ValueError(f'Too many PDF pages (max {MAX_PAGES}).')
            ocr_count = 0
            for i, page in enumerate(pdf):
                if page.rect.width > 4000 or page.rect.height > 4000 or page.rect.width * page.rect.height > 5_000_000:
                    raise ValueError('PDF page dimensions are too large to process safely.')
                text = page.get_text('text', sort=True).strip()
                used_ocr = False
                if len(text) < 35:
                    ocr_count += 1
                    if ocr_count > MAX_OCR_PAGES:
                        raise ValueError(f'Too many scanned PDF pages (max {MAX_OCR_PAGES}).')
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
                    text = _ocr_image(pix.tobytes('png'))
                    used_ocr = True
                if text:
                    pages.append(Page(i+1, text, used_ocr))
    elif suffix == '.docx':
        doc = Document(path)
        lines = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                lines.append(' | '.join(c.text for c in row.cells))
        pages.append(Page(1, '\n'.join(lines)))
    elif suffix == '.pptx':
        pres = Presentation(path)
        if len(pres.slides) > MAX_PAGES:
            raise ValueError('Too many slides.')
        for i, slide in enumerate(pres.slides):
            lines = []
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text.strip():
                    lines.append(shape.text)
                if shape.has_table:
                    lines.extend(' | '.join(c.text for c in row.cells) for row in shape.table.rows)
            if lines:
                pages.append(Page(i+1, '\n'.join(lines)))
    elif suffix in {'.txt', '.md'}:
        content = path.read_text(encoding='utf-8-sig', errors='replace').strip()
        pages = [Page(i // 6500+1, content[i:i+6500]) for i in range(0, len(content), 6500)]
    elif suffix in {'.png', '.jpg', '.jpeg', '.webp'}:
        raw = path.read_bytes()
        text = ''
        try:
            text = _ocr_image(raw)
        except ValueError:
            pass
        try:
            from .local_models import describe_image
            visual = describe_image(raw)
            text = (text + '\n\n' + visual).strip()
        except (ValueError, OSError, TimeoutError):
            if not text:
                raise ValueError('Cannot read this image. Install Tesseract or start local Qwen3.6 27B vision.')
        pages.append(Page(1, text, bool(text)))
    else:
        raise ValueError('Unsupported file format.')
    if not any(x.text.strip() for x in pages):
        raise ValueError('No readable text. Try a clear searchable file.')
    for page in pages:
        page.text = readable_text(page.text)
    return pages
