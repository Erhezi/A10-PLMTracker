from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_file, url_for

from .doc_parser import load_manual_sections

bp = Blueprint("selfawareness", __name__, url_prefix="/doc")

VIDEO_FILENAME = "PLM_Tracker_Workflow.mp4"
CAPTION_FILENAME = "PLM_Tracker_Workflow-en-US.vtt"
MANUAL_FILENAME = "PLM Tracker Onboarding Manual.docx"

# Curated highlights pulled from the onboarding manual so users can skim quickly.
MANUAL_SUMMARY = [
    {
        "title": "Introduction & Purpose",
        "body": (
            "The PLM Tracker is a workflow-first system for Supply Chain and Procurement teams. "
            "It centralizes lifecycle conversions, replacement metadata, conflicts, and documentation "
            "so projects share a single source of truth."
        ),
    },
    {
        "title": "Scope of Use",
        "body": (
            "Use the Tracker for company 3000 inventory items that are undergoing conversions. "
            "It supports 1→1, 1→many, and many→1 replacement scenarios while deliberately excluding "
            "non-conversion work and non-inventory items."
        ),
    },
    {
        "title": "Access & Roles",
        "body": (
            "Registration happens at /auth/register and requires admin approval before login. "
            "Roles determine navigation: admins manage users, analysts operate Collector and Dashboard, "
            "and view-only users focus on analytics without editing powers."
        ),
    },
    {
        "title": "Collector Workflow",
        "body": (
            "Collector is where you build conversion pairs, upload supporting files, and move items "
            "through stage transitions. The manual calls out the allowed relationship structures and "
            "how conflicts are surfaced when unsupported patterns are attempted."
        ),
    },
    {
        "title": "Dashboard & Reporting",
        "body": (
            "The Dashboard delivers self-serve analytics: KPIs, tri-state filters, and exportable "
            "reports that help communicate go-live readiness to stakeholders."
        ),
    },
]


def _ref_dir() -> Path:
    return Path(current_app.root_path).parent / "_ref"


def _resolve_ref_file(filename: str) -> Path:
    path = _ref_dir() / filename
    if not path.exists():
        current_app.logger.warning("Requested documentation asset missing: %s", path)
        abort(404)
    return path


def _load_manual_doc() -> list[dict]:
    manual_path = _resolve_ref_file(MANUAL_FILENAME)
    sections = load_manual_sections(str(manual_path), manual_path.stat().st_mtime)
    return sections


@bp.route("/")
def index():
    return render_template(
        "selfawareness/index.html",
        manual_highlights=MANUAL_SUMMARY,
        manual_doc=_load_manual_doc(),
        manual_download_url=url_for("selfawareness.manual_download"),
    )


@bp.route("/workflow-video")
def workflow_video():
    return send_file(_resolve_ref_file(VIDEO_FILENAME), mimetype="video/mp4")


@bp.route("/workflow-captions")
def workflow_captions():
    return send_file(_resolve_ref_file(CAPTION_FILENAME), mimetype="text/vtt")


@bp.route("/onboarding-manual")
def manual_download():
    return send_file(
        _resolve_ref_file(MANUAL_FILENAME),
        download_name=MANUAL_FILENAME,
        as_attachment=False,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
