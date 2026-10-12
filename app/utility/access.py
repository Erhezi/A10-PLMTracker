"""Module roles and capabilities, plus the two-row navigation.

PLM permissions stay where they are (``users.user_role``: admin / user /
view-only). Fill/Kill roles live in ``PLM.UserModuleRole`` and are turned into
capabilities here, so routes and templates ask ``can(user, "order")`` rather
than checking role codes themselves.
"""

from __future__ import annotations

from functools import wraps

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user

FILLKILL = "fillkill"

ROLE_VIEWER = "viewer"
ROLE_PROPOSER = "proposer"    # A - enters subs
ROLE_CLINICAL = "clinical"    # B - nursing: sub status and picks
ROLE_MATERIALS = "materials"  # C - materials manager: records orders

FILLKILL_ROLES = (ROLE_VIEWER, ROLE_PROPOSER, ROLE_CLINICAL, ROLE_MATERIALS)

ROLE_LABELS = {
    ROLE_VIEWER: "Viewer",
    ROLE_PROPOSER: "A · Sub entry",
    ROLE_CLINICAL: "B · Nursing",
    ROLE_MATERIALS: "C · Materials manager",
}

# Which roles grant each capability. Admins can always view, and hold every
# role by default (seeded / granted on promotion), but act only through roles
# they still hold, so switching one off lets them test as the others.
CAPABILITIES = {
    "view": frozenset(FILLKILL_ROLES),
    "add_sub": frozenset({ROLE_PROPOSER, ROLE_MATERIALS}),
    "review": frozenset({ROLE_CLINICAL}),
    "order": frozenset({ROLE_MATERIALS}),
}

BC_CONFLICT_MESSAGE = (
    "B (Nursing) and C (Materials manager) can't be held by the same person, "
    "except by admins."
)


def is_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and getattr(user, "user_role", None) == "admin"


def fillkill_roles(user) -> frozenset[str]:
    """Fill/Kill role codes the user holds."""
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    return frozenset(
        r.role for r in (getattr(user, "module_roles", None) or []) if r.module == FILLKILL
    )


def can(user, capability: str) -> bool:
    if capability not in CAPABILITIES:
        raise KeyError(f"Unknown Fill/Kill capability: {capability}")
    if not getattr(user, "is_authenticated", False):
        return False
    if capability == "view" and is_admin(user):
        return True
    return bool(fillkill_roles(user) & CAPABILITIES[capability])


def role_conflict(roles, *, admin: bool) -> str | None:
    """Return why this role set isn't allowed, or None."""
    roles = set(roles)
    if not admin and {ROLE_CLINICAL, ROLE_MATERIALS} <= roles:
        return BC_CONFLICT_MESSAGE
    return None


def wants_json() -> bool:
    """True for script calls (appFetch, JSON bodies, /api/ paths) rather than page loads."""
    return bool(
        request.headers.get("X-Requested-With")
        or request.is_json
        or "/api/" in request.path
    )


def require_fillkill(capability: str):
    """Guard a Fill/Kill route. Put it under ``@login_required``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if can(current_user, capability):
                return view(*args, **kwargs)
            if wants_json():
                return jsonify({
                    "error": "forbidden",
                    "message": "Your Fill/Kill roles don't allow this.",
                }), 403
            flash("You don't have access to that Fill/Kill page. Ask an admin for a Fill/Kill role.", "warning")
            return redirect(url_for("main.index"))

        return wrapped

    return decorator


# ---------------------------------------------------------------------------
# Navigation: a module row, then a page row for the active module.
# ---------------------------------------------------------------------------

PLM_BLUEPRINTS = {"collector", "dashboard", "playground"}


def _page(label, endpoint, *, match_blueprint=None):
    if match_blueprint:
        active = request.blueprint == match_blueprint
    else:
        active = request.endpoint == endpoint
    return {"label": label, "url": url_for(endpoint), "active": active}


def _plm_pages(user):
    pages = []
    if user.user_role != "view-only":
        pages.append(_page("Collect", "collector.collect"))
    pages.append(_page("Groups", "collector.groups"))
    if user.user_role != "view-only":
        pages.append(_page("Conflicts", "collector.conflicts"))
    pages.append(_page("Dashboard", "dashboard.index", match_blueprint="dashboard"))
    pages.append(_page("Playground", "playground.index", match_blueprint="playground"))
    return pages


def _fillkill_pages(user):
    return [_page("Main", "fillkill.index")]


DOCS_BLUEPRINT = "selfawareness"
DOCS_ENDPOINTS = {"plm": "selfawareness.index", FILLKILL: "selfawareness.fillkill"}


def _docs_pages():
    return [
        _page("PLM Tracker", DOCS_ENDPOINTS["plm"]),
        _page("Fill/Kill Management", DOCS_ENDPOINTS[FILLKILL]),
    ]


PAGE_ROW_LABELS = {
    "plm": "PLM Tracker pages",
    FILLKILL: "Fill/Kill Management pages",
    "docs": "Docs",
}


def build_nav(user):
    """Navigation for the current request.

    ``modules`` is empty when nobody is logged in; the Docs page row and link
    work either way, since the docs pages are public.
    """
    authenticated = bool(getattr(user, "is_authenticated", False))

    blueprint = request.blueprint
    if blueprint in PLM_BLUEPRINTS:
        active = "plm"
    elif blueprint == FILLKILL:
        active = FILLKILL
    elif blueprint == DOCS_BLUEPRINT:
        active = "docs"
    else:
        active = None

    modules = []
    if authenticated:
        modules.append({
            "key": "plm",
            "label": "PLM Tracker",
            "url": url_for("dashboard.index"),
            "active": active == "plm",
        })
        if can(user, "view"):
            modules.append({
                "key": FILLKILL,
                "label": "Fill/Kill Management",
                "url": url_for("fillkill.index"),
                "active": active == FILLKILL,
            })

    if active == "plm" and authenticated:
        pages = _plm_pages(user)
    elif active == FILLKILL and authenticated:
        pages = _fillkill_pages(user)
    elif active == "docs":
        pages = _docs_pages()
    else:
        pages = []

    # The Docs link opens the docs of the module you're in.
    in_fillkill = active == FILLKILL or request.endpoint == DOCS_ENDPOINTS[FILLKILL]
    docs_url = url_for(DOCS_ENDPOINTS[FILLKILL] if in_fillkill else DOCS_ENDPOINTS["plm"])

    return {
        "modules": modules,
        "active": active,
        "pages": pages,
        "page_row_label": PAGE_ROW_LABELS.get(active, ""),
        "docs_url": docs_url,
    }
