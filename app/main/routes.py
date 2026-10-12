from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required, current_user

from ..utility.access import MODULE_HOMES, MODULES, accessible_modules

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    """Land in the first module the user can open; without any, explain why."""
    modules = accessible_modules(current_user)
    if modules:
        return redirect(url_for(MODULE_HOMES[modules[0].key]))
    requested = [
        MODULES[key].label
        for key in (current_user.requested_modules or "").split(",")
        if key in MODULES
    ]
    return render_template("main/no_access.html", requested=requested)
