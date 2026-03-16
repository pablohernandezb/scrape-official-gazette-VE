# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python scraper that downloads Venezuelan Official Gazette (Gaceta Oficial) PDFs from `http://www.gacetaoficial.gob.ve/`. It targets both ordinary (Ordinaria) and extraordinary (Extraordinaria) gazette series.

## Running the Script

```bash
pip install requests beautifulsoup4
python scrape_gazettes.py
```

## Architecture

The entire project is a single file (`scrape_gazettes.py`) built around one function:

**`download_gaceta_smart(name, start, end)`** — iterates a range of gazette numbers, fetches each gazette's wrapper page at `http://www.gacetaoficial.gob.ve/gacetas/{num}`, extracts the PDF link using two fallback strategies (Strategy A: `<a>` tags with `.pdf` href; Strategy B: `<embed>`/`<iframe>` tags with `.pdf` src), then streams the PDF to `Gacetas_2026_{name}/Gaceta_{num}.pdf`.

Output folders:
- `Gacetas_2026_Ordinaria/` — ordinary gazettes (sequential 5-digit numbers, e.g. 43287)
- `Gacetas_2026_Extraordinaria/` — extraordinary gazettes (4-digit numbers, e.g. 6954)

Missing gazette numbers in output folders are expected — they correspond to numbers that don't exist on the server.
