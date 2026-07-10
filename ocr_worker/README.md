# OCR Worker (optional — only needed to scan purchase bills)

Gemini ERP does OCR in a **separate Python 3.13 environment** because the OCR
engine (PaddleOCR / PaddlePaddle) has no builds for the app's Python 3.14. The
main app calls this folder's `ocr_runner.py` as a subprocess. Everything OCR
needs lives inside this `ocr_worker/` folder:

```
ocr_worker/
  ocr_runner.py        <- the OCR script (run by the 3.13 venv below)
  requirements.txt     <- OCR dependencies
  poppler/bin/         <- bundled Poppler (for PDF bills) — no separate install
  venv_ocr/            <- you create this once, see below
```

## One-time setup (do this in the ocr_worker folder)

1. Install **Python 3.13** from https://www.python.org/downloads/
   (keep it alongside any other Python — the installer offers `py -3.13`).

2. Open a terminal **in this `ocr_worker` folder** and run:

   ```
   py -3.13 -m venv venv_ocr
   venv_ocr\Scripts\activate
   pip install -r requirements.txt
   ```

That's it. Poppler is already included in `poppler/bin` — no separate install
and no PATH changes are required.

## Notes

- The **first** scan downloads the OCR models (needs internet once); they are
  cached afterwards and later scans work offline.
- A scan of a real bill takes a few minutes on CPU — this is expected; the app
  shows a "Scanning…" indicator while it runs.
- If `venv_ocr` is not set up, the app still runs fine — the Scan screen simply
  reports that OCR is not configured instead of crashing. You can always enter
  purchase bills manually.
