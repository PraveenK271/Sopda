"""OCR runner — executed by the SEPARATE Python 3.13 venv (``venv_ocr``).

This is the ONLY file in the codebase that imports PaddleOCR / pdf2image / does
image preprocessing. The main app runs on Python 3.14, for which PaddlePaddle
has no wheels, so ``services/ocr_service.py`` (3.14) invokes this script with
``venv_ocr``'s interpreter as a subprocess and reads a single JSON object from
stdout. Keeping every PaddleOCR touch in this one file is the non-negotiable
rule from ``OCR_Instruction.txt`` — the engine can be swapped (or a cloud
fallback added) by changing only this file.

Contract — stdout carries ONLY the final JSON line; all engine banners, model
download progress and errors go to stderr:

    {"ok": bool, "raw_text": str, "confidence": float, "warnings": [str, ...]}

Never raises to the caller: on any failure it prints ``ok=false`` with a
warning and exits 0, so the main service always gets a parseable result.

Usage: ``python ocr_runner.py <file_path>``

Note: PaddleOCR downloads its detection/recognition models on the first
``PaddleOCR()`` instantiation (needs internet once); they are cached afterwards.
PDF input additionally needs poppler on PATH (see README.md).
"""

import os
import sys

# --- Redirect ALL stdout (Python + native PaddlePaddle C++) to stderr up front,
# so the ONLY thing on real stdout is our final JSON line. Native code writes to
# OS fd 1 directly, so we redirect at the fd level, keeping the original fd for
# the final emit. This must happen before importing paddleocr (its import/init
# print banners to stdout).
_REAL_STDOUT_FD = os.dup(1)
os.dup2(2, 1)


def _emit(payload: dict) -> None:
    """Write the one JSON line to the saved real stdout fd."""
    import json

    os.write(_REAL_STDOUT_FD, (json.dumps(payload) + "\n").encode("utf-8"))


def _error(message: str) -> dict:
    return {"ok": False, "raw_text": "", "confidence": 0.0, "warnings": [message]}


def _preprocess(image):
    """Greyscale + contrast, size-normalise — improves accuracy AND speed.

    Large phone photos (2000-4000px) make CPU OCR extremely slow, so cap the
    long side at 1600px; tiny scans are upscaled so small text stays legible.
    """
    from PIL import ImageEnhance

    image = image.convert("L")
    image = ImageEnhance.Contrast(image).enhance(1.5)
    max_side = max(image.width, image.height)
    if max_side > 1600:
        scale = 1600 / max_side
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    elif image.width < 1000:
        image = image.resize((image.width * 2, image.height * 2))
    # PaddleOCR expects a 3-channel image; convert back after greyscale work.
    return image.convert("RGB")


def _bundled_poppler_path():
    """Return a poppler bin/ shipped next to this script, or None.

    The packaged distribution places poppler at ocr_worker/poppler/bin so PDF
    support travels with the app (no system install / PATH entry needed on the
    target machine). In a dev checkout that folder is absent, so we return None
    and let pdf2image find poppler on PATH — preserving the original behaviour.
    """
    candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poppler", "bin")
    return candidate if os.path.isdir(candidate) else None


def _load_images(file_path: str, warnings: list) -> list:
    """Return a list of PIL images (one per page for PDFs)."""
    from PIL import Image

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path

            poppler_path = _bundled_poppler_path()
            if poppler_path:
                return list(convert_from_path(file_path, poppler_path=poppler_path))
            return list(convert_from_path(file_path))
        except Exception as exc:  # poppler missing is the common cause
            warnings.append(
                f"PDF conversion failed (is poppler installed and on PATH?): {exc}"
            )
            return []
    return [Image.open(file_path)]


def _get(res, key):
    """Read a field from a PaddleOCR 3.x result (dict-like or attribute)."""
    try:
        return res[key]
    except Exception:
        return getattr(res, key, None)


def _run(file_path: str) -> dict:
    warnings: list[str] = []
    images = _load_images(file_path, warnings)
    if not images:
        return {"ok": False, "raw_text": "", "confidence": 0.0, "warnings": warnings}

    import numpy as np
    from paddleocr import PaddleOCR

    # Config tuned on real supplier bills (see CHECKLIST_PHASE3.md Milestone 21):
    #  * mobile det/rec models — the default PP-OCRv6 *medium* models take ~350s
    #    per bill on CPU and time out; mobile finishes in ~1/2 that with ~0.93
    #    confidence, which is plenty for a user-confirmed workflow.
    #  * enable_mkldnn=False — mkldnn crashes on this PaddlePaddle 3.x build
    #    ("ConvertPirAttribute2RuntimeAttribute ... onednn_instruction.cc"),
    #    even with the PIR executor disabled, so it cannot be used here.
    #  * doc-orientation / unwarping OFF — heavy models we don't need for flat
    #    scans. Consequence: a page rotated a full 90 deg reads poorly; users
    #    should upload upright scans (a rotate step can be added to the UI later).
    engine = PaddleOCR(
        lang="en",
        use_textline_orientation=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        enable_mkldnn=False,
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="PP-OCRv5_mobile_rec",
        text_recognition_batch_size=8,
    )

    all_text: list[str] = []
    all_scores: list[float] = []
    for image in images:
        arr = np.array(_preprocess(image))
        for res in engine.predict(arr):
            texts = _get(res, "rec_texts") or []
            scores = _get(res, "rec_scores") or []
            all_text.extend(t for t in texts if t)
            all_scores.extend(float(s) for s in scores)

    if not all_text:
        warnings.append("No text detected in the document.")

    confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
    return {
        "ok": True,
        "raw_text": "\n".join(all_text),
        "confidence": confidence,
        "warnings": warnings,
    }


def main() -> None:
    if len(sys.argv) < 2:
        _emit(_error("No file path provided to OCR runner."))
        return
    file_path = sys.argv[1]
    if not os.path.isfile(file_path):
        _emit(_error(f"File not found: {file_path}"))
        return
    try:
        _emit(_run(file_path))
    except Exception as exc:  # never crash the caller
        _emit(_error(f"OCR failed: {exc}"))


if __name__ == "__main__":
    main()
