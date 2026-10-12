"""Fill/Kill Management module (design: _ref/FillKill/fillkill_design.md).

Deploy #1 ships only the entry page; the main table, subs and orders follow in
deploy #2.
"""

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from ..utility.access import ROLE_LABELS, FILLKILL_ROLES, fillkill_roles, is_admin, require_fillkill

bp = Blueprint("fillkill", __name__, url_prefix="/fillkill")


@bp.route("/")
@login_required
@require_fillkill("view")
def index():
    held = fillkill_roles(current_user)
    roles = [ROLE_LABELS[code] for code in FILLKILL_ROLES if code in held]
    return render_template("fillkill/index.html", roles=roles, admin=is_admin(current_user))
