from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required, current_user

from ..utility.access import MODULE_HOMES, MODULES, accessible_modules, is_admin

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    """Land in the first module the user can open; without any, explain why.

    An admin with no module role lands in User Control, where they can give themselves one.
    """
    modules = accessible_modules(current_user)
    if modules:
        return redirect(url_for(MODULE_HOMES[modules[0].key]))
    if is_admin(current_user):
        return redirect(url_for("admin.user_control"))
    requested = [
        MODULES[key].label
        for key in (current_user.requested_modules or "").split(",")
        if key in MODULES
    ]
    return render_template("main/no_access.html", requested=requested)
