"""
OCR-based extraction for image-based gazette pages.
Used as a fallback when normal text extraction fails for collective entries.
"""

import fitz
import pytesseract
import io
import re
import os
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
os.environ['TESSDATA_PREFIX'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tessdata')


def ocr_page(doc, page_idx, zoom=2.5):
    """OCR a single page, returns text."""
    page = doc[page_idx]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes('png')))
    return pytesseract.image_to_string(img, lang='spa')


def page_needs_ocr(doc, page_idx):
    """Check if a page is mostly image-based (needs OCR)."""
    page = doc[page_idx]
    text_len = len(page.get_text().strip())
    num_images = len(page.get_images())
    return num_images > 3 and text_len < 500


def ocr_gazette_body(pdf_path):
    """OCR all image-based body pages. Returns full OCR text."""
    doc = fitz.open(pdf_path)
    ocr_text = ""
    for i in range(1, len(doc) - 1):
        if page_needs_ocr(doc, i):
            try:
                text = ocr_page(doc, i)
                ocr_text += f"\n--- PAGE {i+1} ---\n" + text
            except Exception as e:
                print(f"  OCR error page {i+1}: {e}")
    doc.close()
    return ocr_text


def extract_designations_from_ocr(ocr_text):
    """Extract person-post pairs from OCR text.
    Returns list of dicts: name, post, institution."""
    results = []

    # Work with both raw (line-preserved) and normalized text
    norm = re.sub(r'\s+', ' ', ocr_text)

    # ── Pattern 1: "NAME, titular de la cédula... como POST" (universal) ──
    # This is the most reliable pattern — catches Designar, Nombrar, and any variation
    for m in re.finditer(
        r'(?:ciudadana?|ciudadano)\s+'
        r'([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜa-záéíóúñü\s]{5,60}?)'
        r'(?:\s*,\s*titular|\s+titular)'
        r'[^§]{10,200}?'
        r'como\s+(.+?)(?:\s*(?:,\s*(?:con\s+las|adscrit|del\s+Minister|en\s+condici)|[.]\s|$))',
        norm, re.IGNORECASE
    ):
        name = m.group(1).strip()
        post = m.group(2).strip()
        if len(name) > 5 and 'CEDULA' not in name.upper():
            results.append({"name": name, "post": post, "institution": ""})

    # ── Pattern 3: TITLE line followed by NAME and V-CEDULA ──
    # Junta format: "PRESIDENTE DE LA JUNTA\nNAME\nV-12345"
    for m in re.finditer(
        r'((?:PRESIDENTE?A?|VICEPRESIDENTE?A?|DIRECTOR(?:A)?|MIEMBRO|SECRETARI[OA]|VOCAL|SUPLENTE|PRINCIPAL)'
        r'[A-ZÁÉÍÓÚÑÜa-záéíóúñü\s()]*?)'
        r'[\s\n]+'
        r'([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜa-záéíóúñü\s]{5,50}?)'
        r'\s*(?:V-?\s*[\d.]+|C\.?I\.?\s*:?\s*V)',
        ocr_text, re.IGNORECASE
    ):
        post = re.sub(r'\s+', ' ', m.group(1)).strip()
        name = re.sub(r'\s+', ' ', m.group(2)).strip()
        if len(name) > 5 and 'CEDULA' not in name.upper() and 'CARGO' not in name.upper():
            results.append({"name": name, "post": post, "institution": ""})

    # ── Pattern 4: Table rows — find V-CEDULA (various OCR formats), look backwards for name ──
    for m in re.finditer(r'V[-.:;]?\s*[\d][\d.:, -]{4,}', ocr_text):
        start = max(0, m.start() - 120)
        pre = ocr_text[start:m.start()]
        pre_clean = re.sub(r'[|]', ' ', pre)
        pre_clean = re.sub(r'\s+', ' ', pre_clean).strip()
        # Find last sequence of name-like words before cédula
        nm = re.search(
            r'([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,5})\s*$',
            pre_clean
        )
        if nm:
            raw = nm.group(1).strip()
            raw = re.sub(r'^\d+\s+', '', raw)
            skip_words = ['CEDULA', 'CARGO', 'NOMBRE', 'APELLIDO', 'ARTICULO',
                          'RESOLUCI', 'GACETA', 'MINISTERIO', 'REPUBLICA',
                          'IDENTIDAD', 'BOLIVARIANA', 'VENEZUELA', 'POPULAR',
                          'OFICIAL', 'DESPACHO', 'CIUDADAN']
            if any(w in raw.upper() for w in skip_words):
                continue
            words = [w for w in raw.split() if len(w) > 1]
            if len(words) >= 2 and len(raw) > 8:
                post_text = re.sub(r'\s+', ' ', ocr_text[m.end():m.end()+200]).strip()
                pm = re.search(r'(DIRECTOR[^.;]{10,80})', post_text, re.IGNORECASE)
                post = pm.group(1).strip() if pm else ""
                results.append({"name": raw, "post": post, "institution": ""})

    # Deduplicate by normalized name
    seen = set()
    unique = []
    for r in results:
        key = re.sub(r'\s+', ' ', r["name"].upper().strip())
        if key not in seen and len(key) > 5:
            seen.add(key)
            unique.append(r)

    return unique


if __name__ == "__main__":
    import sys
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Gacetas_2026_Ordinaria/Gaceta_43317.pdf"
    print(f"OCR extracting from {pdf_path}...")
    ocr_text = ocr_gazette_body(pdf_path)
    print(f"OCR text: {len(ocr_text)} chars")
    results = extract_designations_from_ocr(ocr_text)
    print(f"\nExtracted {len(results)} designations:")
    for r in results:
        print(f"  {r['name'][:45]:45s} | {r['post'][:55]}")
