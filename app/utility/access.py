"""Users, modules and roles for the whole app, plus the two-row navigation.

An account (``PLM.users``) is registered and approved once. What someone can
do is set per module in ``PLM.UserModuleRole``:

    app       admin                                     manage users; see every module
    plm       viewer | editor                           at most one of the two
    fillkill  viewer, proposer (A), clinical (B), materials (C)

Routes and templates ask ``can(user, module, capability)`` instead of checking
role codes. ``users.user_role`` is no longer read; ``apply_access`` keeps it
in step (see ``legacy_user_role``) so the previous release still works if it
has to be redeployed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user

APP = "app"
PLM = "plm"
FILLKILL = "fillkill"

ADMIN = "admin"

PLM_VIEWER = "viewer"
PLM_EDITOR = "editor"

ROLE_VIEWER = "viewer"
ROLE_PROPOSER = "proposer"    # A - enters subs
ROLE_CLINICAL = "clinical"    # B - nursing: sub status and picks
ROLE_MATERIALS = "materials"  # C - materials manager: records orders


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    roles: tuple[tuple[str, str], ...]          # (code, label), in display order
    capabilities: dict[str, frozenset[str]] = field(default_factory=dict)
    single_role: bool = False                   # True: hold at most one role

    @property
    def role_codes(self) -> tuple[str, ...]:
        return tuple(code for code, _ in self.roles)

    def role_label(self, code: str) -> str:
        return dict(self.roles)[code]


MODULES = {
    PLM: Module(
        key=PLM,
        label="PLM Tracker",
        roles=((PLM_VIEWER, "Viewer"), (PLM_EDITOR, "Editor")),
        capabilities={
            "view": frozenset({PLM_VIEWER, PLM_EDITOR}),
            "edit": frozenset({PLM_EDITOR}),
        },
        single_role=True,
    ),
    FILLKILL: Module(
        key=FILLKILL,
        label="Fill/Kill Management",
        roles=(
            (ROLE_VIEWER, "Viewer"),
            (ROLE_PROPOSER, "A · Sub entry"),
            (ROLE_CLINICAL, "B · Nursing"),
            (ROLE_MATERIALS, "C · Materials manager"),
        ),
        capabilities={
            "view": frozenset({ROLE_VIEWER, ROLE_PROPOSER, ROLE_CLINICAL, ROLE_MATERIALS}),
            "add_sub": frozenset({ROLE_PROPOSER, ROLE_MATERIALS}),
            "review": frozenset({ROLE_CLINICAL}),
            "order": frozenset({ROLE_MATERIALS}),
        },
    ),
}

BC_CONFLICT_MESSAGE = (
    "B (Nursing) and C (Materials manager) can't be held by the same person, "
    "except by admins."
)


# ---------------------------------------------------------------------------
# Reading roles
# ---------------------------------------------------------------------------

def _authenticated(user) -> bool:
    return bool(getattr(user, "is_authenticated", False))


def roles_in(user, module: str) -> frozenset[str]:
    """Role codes the user holds in one module (``app`` included)."""
    if not _authenticated(user):
        return frozenset()
    return frozenset(
        r.role for r in (getattr(user, "module_roles", None) or []) if r.module == module
    )


def is_admin(user) -> bool:
    return ADMIN in roles_in(user, APP)


def can(user, module: str, capability: str) -> bool:
    """Whether the user may do ``capability`` in ``module``. Admins can always view."""
    allowed = MODULES[module].capabilities[capability]  # KeyError on a typo, on purpose
    if not _authenticated(user):
        return False
    if capability == "view" and is_admin(user):
        return True
    return bool(roles_in(user, module) & allowed)


def accessible_modules(user) -> list[Module]:
    return [module for module in MODULES.values() if can(user, module.key, "view")]


def validate_roles(*, admin: bool, roles: dict[str, set[str]]) -> str | None:
    """Why this combination isn't allowed, or None."""
    for key, codes in roles.items():
        module = MODULES[key]
        unknown = set(codes) - set(module.role_codes)
        if unknown:
            return f"Unknown {module.label} role: {', '.join(sorted(unknown))}."
        if module.single_role and len(codes) > 1:
            return f"Pick one {module.label} role."
    fillkill = set(roles.get(FILLKILL, ()))
    if not admin and {ROLE_CLINICAL, ROLE_MATERIALS} <= fillkill:
        return BC_CONFLICT_MESSAGE
    return None


def legacy_user_role(*, admin: bool, plm_roles) -> str:
    """The users.user_role value the previous release understands."""
    if admin:
        return "admin"
    if PLM_EDITOR in plm_roles:
        return "user"
    return "view-only"  # least access the old code can express


def role_summary(user) -> str:
    """'Admin; PLM Tracker: Editor; Fill/Kill Management: Viewer' or 'no access'."""
    parts = ["Admin"] if is_admin(user) else []
    for module in MODULES.values():
        held = roles_in(user, module.key)
        if held:
            labels = ", ".join(module.role_label(c) for c in module.role_codes if c in held)
            parts.append(f"{module.label}: {labels}")
    return "; ".join(parts) if parts else "no access"


# ---------------------------------------------------------------------------
# Changing roles (no commit; the caller commits)
# ---------------------------------------------------------------------------

def _set_module_roles(user, module: str, wanted, granted_by: str) -> None:
    from sqlalchemy.orm import object_session

    from ..models import now_ny_naive
    from ..models.auth import UserModuleRole

    wanted = set(wanted)
    removed = False
    for row in list(user.module_roles):
        if row.module == module and row.role not in wanted:
            user.module_roles.remove(row)
            removed = True
    # Delete before inserting: the flush would otherwise insert first, and swapping
    # PLM Viewer <-> Editor would trip the one-PLM-role-per-user index.
    session = object_session(user)
    if removed and session is not None:
        session.flush()
    held = roles_in(user, module)
    for code in sorted(wanted - held):
        user.module_roles.append(UserModuleRole(
            module=module, role=code, granted_by=granted_by, granted_at=now_ny_naive(),
        ))


def apply_access(user, *, admin: bool, roles: dict[str, set[str]], granted_by: str) -> None:
    """Set the user's admin flag and module roles, and keep users.user_role in step."""
    _set_module_roles(user, APP, {ADMIN} if admin else set(), granted_by)
    for key, codes in roles.items():
        _set_module_roles(user, key, codes, granted_by)
    user.user_role = legacy_user_role(admin=admin, plm_roles=roles_in(user, PLM))


def full_access_roles() -> dict[str, set[str]]:
    """What a new admin starts with: every module's top roles."""
    return {PLM: {PLM_EDITOR}, FILLKILL: set(MODULES[FILLKILL].role_codes)}


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def wants_json() -> bool:
    """True for script calls (appFetch, JSON bodies, /api/ paths) rather than page loads."""
    return bool(
        request.headers.get("X-Requested-With")
        or request.is_json
        or "/api/" in request.path
    )


def deny(message: str):
    """Refuse in a way that suits the request; pages go back to the landing page."""
    if wants_json() or request.headers.get("HX-Request") == "true":
        return jsonify({"error": "forbidden", "message": message}), 403
    flash(message, "warning")
    return redirect(url_for("main.index"))


DENIED_MESSAGES = {
    (PLM, "view"): "You don't have access to PLM Tracker. Ask an admin for a PLM role.",
    (PLM, "edit"): "Your PLM Tracker role is Viewer, so you can't make changes.",
    (FILLKILL, "view"): "You don't have access to Fill/Kill Management. Ask an admin for a Fill/Kill role.",
}


def require_module(module: str, capability: str):
    """Guard a route. Put it under ``@login_required``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if can(current_user, module, capability):
                return view(*args, **kwargs)
            return deny(DENIED_MESSAGES.get(
                (module, capability), f"Your {MODULES[module].label} roles don't allow this."
            ))

        return wrapped

    return decorator


# PLM is guarded per request rather than per route: its views predate module roles.
PLM_BLUEPRINTS = {"collector", "dashboard", "playground"}
PLM_EDITOR_PAGES = {"collector.collect", "collector.conflicts"}   # editor-only even to look at
PLM_READ_ONLY_POSTS = {"collector.batch_export_wrike_item_numbers"}  # POST, but only reads
PLM_ADMIN_ENDPOINTS = {"collector.clear_deleted", "collector.archive_completed"}  # checked in the view


def plm_capability_for(endpoint: str | None, blueprint: str | None, method: str) -> str | None:
    """The PLM capability a request needs, or None when the view checks it itself."""
    if endpoint in PLM_ADMIN_ENDPOINTS:
        return None
    if endpoint in PLM_EDITOR_PAGES:
        return "edit"
    if blueprint == "collector" and method not in ("GET", "HEAD", "OPTIONS"):
        return "view" if endpoint in PLM_READ_ONLY_POSTS else "edit"
    return "view"  # pages, reads, and the dashboard's filter POSTs


def guard_plm_request():
    """before_request: PLM pages need a PLM role; changes need Editor."""
    if request.blueprint not in PLM_BLUEPRINTS or request.endpoint is None:
        return None
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    capability = plm_capability_for(request.endpoint, request.blueprint, request.method)
    if capability is None or can(current_user, PLM, capability):
        return None
    return deny(DENIED_MESSAGES[(PLM, capability)])


def template_helpers():
    """Context processor: ``user_can('plm', 'edit')`` and ``user_is_admin`` in templates."""
    return {
        "user_can": lambda module, capability: can(current_user, module, capability),
        "user_is_admin": is_admin(current_user),
        "nav": build_nav(current_user),
    }


# ---------------------------------------------------------------------------
# Navigation: a module row, then a page row for the active module.
# ---------------------------------------------------------------------------

def _page(label, endpoint, *, match_blueprint=None):
    if match_blueprint:
        active = request.blueprint == match_blueprint
    else:
        active = request.endpoint == endpoint
    return {"label": label, "url": url_for(endpoint), "active": active}


def _plm_pages(user):
    editor = can(user, PLM, "edit")
    pages = []
    if editor:
        pages.append(_page("Collect", "collector.collect"))
    pages.append(_page("Groups", "collector.groups"))
    if editor:
        pages.append(_page("Conflicts", "collector.conflicts"))
    pages.append(_page("Dashboard", "dashboard.index", match_blueprint="dashboard"))
    pages.append(_page("Playground", "playground.index", match_blueprint="playground"))
    return pages


def _fillkill_pages(user):
    return [_page("Main", "fillkill.index")]


MODULE_HOMES = {PLM: "dashboard.index", FILLKILL: "fillkill.index"}
MODULE_PAGES = {PLM: _plm_pages, FILLKILL: _fillkill_pages}

DOCS_BLUEPRINT = "selfawareness"
DOCS_ENDPOINTS = {PLM: "selfawareness.index", FILLKILL: "selfawareness.fillkill"}


def _docs_pages():
    return [_page(MODULES[key].label, endpoint) for key, endpoint in DOCS_ENDPOINTS.items()]


def build_nav(user):
    """Navigation for the current request.

    ``modules`` holds the modules the user can open (none when logged out);
    the Docs page row and link work either way, since the docs are public.
    """
    blueprint = request.blueprint
    if blueprint in PLM_BLUEPRINTS:
        active = PLM
    elif blueprint == FILLKILL:
        active = FILLKILL
    elif blueprint == DOCS_BLUEPRINT:
        active = "docs"
    else:
        active = None

    modules = [
        {
            "key": module.key,
            "label": module.label,
            "url": url_for(MODULE_HOMES[module.key]),
            "active": active == module.key,
        }
        for module in accessible_modules(user)
    ]

    if active in MODULE_PAGES and can(user, active, "view"):
        pages = MODULE_PAGES[active](user)
        page_row_label = f"{MODULES[active].label} pages"
    elif active == "docs":
        pages = _docs_pages()
        page_row_label = "Docs"
    else:
        pages = []
        page_row_label = ""

    # The Docs link opens the docs of the module you're in.
    in_fillkill = active == FILLKILL or request.endpoint == DOCS_ENDPOINTS[FILLKILL]
    docs_url = url_for(DOCS_ENDPOINTS[FILLKILL] if in_fillkill else DOCS_ENDPOINTS[PLM])

    return {
        "modules": modules,
        "active": active,
        "pages": pages,
        "page_row_label": page_row_label,
        "docs_url": docs_url,
    }
