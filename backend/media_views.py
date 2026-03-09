import os
import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404


def _safe_join(base: str, *paths: str) -> str:
    # Prevent path traversal: normalize and ensure result starts with base
    final_path = os.path.normpath(os.path.join(base, *paths))
    base_norm = os.path.normpath(base)
    if not final_path.startswith(base_norm):
        raise Http404("Invalid path")
    return final_path


def serve_media(request, path: str):
    """Serve files from MEDIA_ROOT with correct headers.

    - PDFs are served inline for browser viewing.
    - Other files are served as attachment (download/open externally).
    - Backward-compatible: if file isn't found at given path, tries common legacy locations.
    """
    if not path:
        raise Http404("File not found")

    # Normalize possible leading slashes and duplicate "media/" prefix
    path = path.lstrip("/")
    if path.startswith("media/"):
        path = path[len("media/"):]

    # Candidate locations (support both correct and legacy storage paths)
    candidates = [
        path,
        os.path.join("course_docs", os.path.basename(path)),  # new recommended folder
        os.path.join("course_pdfs", os.path.basename(path)),  # legacy folder
        os.path.basename(path),  # legacy root media
    ]

    file_path = None
    for rel in candidates:
        candidate = _safe_join(settings.MEDIA_ROOT, rel)
        if os.path.exists(candidate) and os.path.isfile(candidate):
            file_path = candidate
            break

    if not file_path:
        raise Http404("File not found")

    guessed_type, _ = mimetypes.guess_type(file_path)
    content_type = guessed_type or "application/octet-stream"

    # PDF inline, others attachment
    is_pdf = False
    try:
        with open(file_path, "rb") as f:
            is_pdf = f.read(4) == b"%PDF"
    except Exception:
        is_pdf = content_type == "application/pdf"

    if is_pdf:
        content_type = "application/pdf"

    resp = FileResponse(open(file_path, "rb"), content_type=content_type)
    if is_pdf:
        resp["Content-Disposition"] = "inline"
    else:
        resp["Content-Disposition"] = f'attachment; filename="{os.path.basename(file_path)}"'
    return resp
