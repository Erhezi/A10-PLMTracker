"""Fill/Kill Management module (design: _ref/FillKill/fillkill_design.md).

Deploy #1 ships only the entry page; the main table, subs and orders follow in
deploy #2.
"""

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from ..utility.access import FILLKILL, MODULES, require_module, roles_in

bp = Blueprint("fillkill", __name__, url_prefix="/fillkill")


@bp.route("/")
@login_required
@require_module(FILLKILL, "view")
def index():
    module = MODULES[FILLKILL]
    held = roles_in(current_user, FILLKILL)
    roles = [label for code, label in module.roles if code in held]
    return render_template("fillkill/index.html", roles=roles)
