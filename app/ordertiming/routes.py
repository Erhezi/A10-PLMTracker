"""Order Timing (2026-10-30): a module beside Fill/Kill, for display.

Medline sends a feed of the EDI orders it received from us, which it fills through the day. These
pages will show it; its data isn't ready, so for now they say so. Every Fill/Kill role can view them
(``access.MODULES[ORDERTIMING]`` has no roles of its own).
"""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

from ..utility.access import ORDERTIMING, require_module

bp = Blueprint("ordertiming", __name__, url_prefix="/ordertiming")


@bp.route("/")
@login_required
@require_module(ORDERTIMING, "view")
def index():
    return render_template("ordertiming/index.html")


@bp.route("/dashboard")
@login_required
@require_module(ORDERTIMING, "view")
def dashboard_page():
    return render_template("ordertiming/dashboard.html")
