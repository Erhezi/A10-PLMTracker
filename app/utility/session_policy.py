"""Daily login reset and how expired logins are answered.

Every login ends at ``LOGIN_RESET_TIME`` (New York time, default 02:30). The
first request after that logs the user out and sends them to the login page,
then back to where they were. A failed CSRF check and a request from someone
not logged in are answered the same way, in a form that suits the request:

- a page load gets a flash message and a redirect to the login page;
- a script call (``appFetch`` sends ``X-Requested-With``) gets a 401 JSON body
  that ``appFetch`` turns into the same redirect;
- an htmx request gets an ``HX-Redirect`` header, so the whole page moves to
  the login form instead of the form appearing inside a results box.

Times are compared as naive New York wall-clock times, like the rest of the
app (``now_ny_naive``), which also keeps the two daylight-saving Sundays right.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from urllib.parse import urlsplit

from flask import current_app, flash, jsonify, make_response, redirect, request, session, url_for
from flask_login import current_user, logout_user
from flask_wtf.csrf import CSRFError

from ..models import now_ny_naive
from .access import wants_json

SESSION_KEY = "login_at"

GENERIC_EXPIRED_MESSAGE = "Your login has expired. Please log in again to continue."
LOGIN_REQUIRED_MESSAGE = "Please log in to access this page."


def _now() -> datetime:
    """Current New York time; a function so tests can move the clock."""
    return now_ny_naive()


def parse_reset_time(value) -> time | None:
    """'02:30' -> time(2, 30); empty disables the reset."""
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    hours, minutes = str(value).strip().split(":")
    return time(int(hours), int(minutes))


def last_reset(now: datetime, reset_at: time) -> datetime:
    """The most recent reset moment at or before ``now``."""
    today = datetime.combine(now.date(), reset_at)
    return today if now >= today else today - timedelta(days=1)


def login_expired(login_at: datetime | None, now: datetime, reset_at: time | None) -> bool:
    if reset_at is None:
        return False
    if login_at is None:
        return True  # logged in before login times were recorded
    return login_at < last_reset(now, reset_at)


def reset_label(reset_at: time) -> str:
    """time(2, 30) -> '2:30 AM'."""
    return reset_at.strftime("%I:%M %p").lstrip("0")


def safe_next(value, script_root: str = "") -> str | None:
    """Accept only a path inside this app; return it without the app prefix.

    Rejects anything that could send the user to another site (absolute URLs,
    protocol-relative ``//host`` paths, backslash tricks).
    """
    if not value:
        return None
    value = str(value).strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    if script_root and (value == script_root or value.startswith(script_root + "/")):
        value = value[len(script_root):] or "/"
    return value


def mark_login() -> None:
    """Record when this login started; called by the login view."""
    session[SESSION_KEY] = _now().isoformat(timespec="seconds")


def clear_login() -> None:
    session.pop(SESSION_KEY, None)


def _login_at() -> datetime | None:
    raw = session.get(SESSION_KEY)
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _same_host_path(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.netloc and parts.netloc != request.host:
        return None
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return safe_next(path, request.script_root)


def _return_path() -> str | None:
    """Where to send the user back to after logging in."""
    if _is_htmx():
        return _same_host_path(request.headers.get("HX-Current-URL"))
    if request.method == "GET":
        qs = request.query_string.decode("utf-8", "replace")
        return safe_next(request.path + (f"?{qs}" if qs else ""))
    # A form post: come back to the page the form was on, not the POST target.
    return _same_host_path(request.referrer)


def login_redirect_response(message: str, category: str = "warning"):
    """Send the user to the login page in a way that suits the request."""
    flash(message, category)
    if _is_htmx():
        response = make_response("", 204)
        response.headers["HX-Redirect"] = url_for("auth.login", next=_return_path())
        return response
    if wants_json():
        return jsonify({
            "error": "login_expired",
            "message": message,
            "login_url": url_for("auth.login"),
        }), 401
    return redirect(url_for("auth.login", next=_return_path()))


def _reset_time():
    return parse_reset_time(current_app.config.get("LOGIN_RESET_TIME"))


def enforce_daily_login():
    """before_request: log out anyone whose login predates the last reset."""
    if request.endpoint in (None, "static"):
        return None
    if not current_user.is_authenticated:
        return None
    reset_at = _reset_time()
    login_at = _login_at()
    if not login_expired(login_at, _now(), reset_at):
        return None
    logout_user()
    clear_login()
    if login_at is None:
        message = GENERIC_EXPIRED_MESSAGE
    else:
        message = f"Your login expired at {reset_label(reset_at)}. Please log in again to continue."
    return login_redirect_response(message)


def handle_csrf_error(error: CSRFError):
    """A missing or stale CSRF token: treat it as an expired login."""
    current_app.logger.warning(
        "CSRF check failed on %s %s: %s", request.method, request.path, error.description
    )
    return login_redirect_response(GENERIC_EXPIRED_MESSAGE)


def handle_unauthorized():
    """Flask-Login's unauthorized handler (login_required on an anonymous request)."""
    if _is_htmx() or wants_json():
        return login_redirect_response(GENERIC_EXPIRED_MESSAGE)
    return login_redirect_response(LOGIN_REQUIRED_MESSAGE, "info")


def init_app(app, login_manager) -> None:
    """Register the hook and handlers. Call before CSRFProtect so this check runs first."""
    app.before_request(enforce_daily_login)
    app.register_error_handler(CSRFError, handle_csrf_error)
    login_manager.unauthorized_handler(handle_unauthorized)
