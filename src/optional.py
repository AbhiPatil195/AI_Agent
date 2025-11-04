from __future__ import annotations


def have_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401

        return True
    except Exception:
        return False


def have_docx() -> bool:
    try:
        import docx  # noqa: F401

        return True
    except Exception:
        return False


def have_reportlab() -> bool:
    try:
        import reportlab  # noqa: F401

        return True
    except Exception:
        return False


def have_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False

