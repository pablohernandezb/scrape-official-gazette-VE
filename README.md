# Scraper — Gaceta Oficial de Venezuela

Downloads Venezuelan Official Gazette (Gaceta Oficial) PDFs and extracts government-change records into a CSV database.

---

## Scripts

### `scrape_gazettes.py` — Download PDFs

Downloads gazette PDFs from [gacetaoficial.gob.ve](http://www.gacetaoficial.gob.ve/).

**Requirements:** `pip install requests beautifulsoup4`

```bash
python scrape_gazettes.py
```

For each gazette number in the configured range it:
1. Fetches the wrapper page at `http://www.gacetaoficial.gob.ve/gacetas/{num}`
2. Finds the PDF link (Strategy A: `<a>` tag with `.pdf` href; Strategy B: `<embed>`/`<iframe>` tag with `.pdf` src)
3. Streams the file to disk

Output folders:

| Folder | Series | Number format |
|---|---|---|
| `Gacetas_2026_Ordinaria/` | Ordinaria | 5-digit (e.g. `43287`) |
| `Gacetas_2026_Extraordinaria/` | Extraordinaria | 4-digit (e.g. `6954`) |

Files are named `Gaceta_{num}.pdf`. Gaps in the sequence are normal — they correspond to numbers that don't exist on the server.

To change the range, edit the two calls at the bottom of the script:

```python
download_gaceta_smart("Ordinaria",      43287, 43325)
download_gaceta_smart("Extraordinaria",  6954,  6990)
```

---

### `extract_changes.py` — Extract government changes to CSV

Processes all downloaded PDFs and writes `cambios_gobierno_2026.csv`.

**Requirements:** `pip install pymupdf`

```bash
python extract_changes.py
```

**Pipeline per gazette:**

1. **Text extraction** — `extract_text()` reads all pages with PyMuPDF (`fitz`)
2. **SUMARIO parsing** — `parse_sumario_entries()` splits the gazette index into individual entries, assigning each to its section header (ministry/institution)
3. **Multi-person splitting** — `split_multi_person_entry()` expands collective designations into one record per person
4. **Body parsing** — `parse_body_decrees()` reads decree articles for detailed name/post data (`Nombro al ciudadano ...`, `se designa al ciudadano ...`)
5. **Classification** — `classify_change()` assigns a change type (e.g. `DESIGNACION_MINISTRO`, `SUPRESION_MINISTERIO`, `JUBILACION`, `REFORMA_LEGISLATIVA`, ~50 categories)
6. **Enrichment** — name, post, institution, and parent organism are extracted and cross-referenced between the SUMARIO and body data
7. **OCR fallback** — if collective designation pages are image-based, `ocr_extract.py` is called automatically (requires Tesseract, see below)
8. **Casing normalization** — all text fields are converted to Spanish title case, preserving acronyms

**CSV columns:**

| Column | Description |
|---|---|
| `gazette_number` | Gazette number |
| `gazette_type` | `Ordinaria` or `Extraordinaria` |
| `gazette_date` | Date as `YYYY-MM-DD` |
| `decree_number` | Decree/resolution number if present |
| `change_type` | Category (e.g. `DESIGNACION_MINISTRO`) |
| `person_name` | Name of the person designated/affected |
| `post_or_position` | Post or position title |
| `institution` | Specific sub-institution (e.g. `SENIAT`, `Fiscalía 5ª`) |
| `organism` | Parent ministry or organism |
| `is_military_person` | `SI` / `NO` |
| `military_rank` | Military rank if applicable |
| `is_military_post` | `SI` / `NO` |
| `summary` | First 500 chars of the source entry |

---

### `ocr_extract.py` — OCR fallback for image-based pages

Called automatically by `extract_changes.py` when needed. Can also be run standalone:

```bash
python ocr_extract.py Gacetas_2026_Ordinaria/Gaceta_43317.pdf
```

**Requirements:**
- `pip install pymupdf pillow pytesseract`
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Spanish language data (`spa.traineddata`) placed in a `tessdata/` folder next to the scripts

**How it works:**

1. `page_needs_ocr()` — flags a page as image-based if it has >3 images and <500 chars of selectable text
2. `ocr_page()` — renders the page at 2.5× zoom and runs Tesseract with Spanish (`spa`) language
3. `extract_designations_from_ocr()` — applies regex patterns to the OCR text to find person–post pairs:
   - Pattern 1: `ciudadano/a NAME, titular de la cédula ... como POST`
   - Pattern 3: title-line format (`PRESIDENTE DE LA JUNTA\nNAME\nV-12345`)
   - Pattern 4: table rows identified by `V-CÉDULA` with name lookup in the preceding text

Results are deduplicated by normalized name and returned as `[{"name": ..., "post": ..., "institution": ...}]`.
