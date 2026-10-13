from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from ..models.auth import User
from ..models import now_ny_naive
from ..utility.msgraph import send_mail
from ..utility.access import (
    FILLKILL,
    MODULES,
    PLM,
    apply_access,
    is_admin,
    role_summary,
    roles_in,
    validate_roles,
)
from .. import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/documents/user-control')
@login_required
def user_control_doc():
    return render_template('documents/userControlGuide.html')


@admin_bp.before_request
def restrict_to_admin():
    if not current_user.is_authenticated:
        flash('Access denied: Please log in.', 'danger')
        return redirect(url_for('auth.login'))

    if not getattr(current_user, 'is_active', False):
        flash('Access denied: Your account is inactive.', 'danger')
        return redirect(url_for('auth.login'))

    if not is_admin(current_user):
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('main.index'))


@admin_bp.route('/user-control')
@login_required
def user_control():
    users = User.query.all()
    rows = [
        {
            'user': u,
            'admin': is_admin(u),
            'roles': {key: roles_in(u, key) for key in MODULES},
            'requested': [
                MODULES[key].label
                for key in (u.requested_modules or '').split(',')
                if key in MODULES
            ],
        }
        for u in users
    ]
    return render_template('admin/user_control.html', rows=rows, modules=MODULES)


@admin_bp.route('/update-access/<string:user_email>', methods=['POST'])
@login_required
def update_access(user_email):
    """Save one user's admin flag and module roles (one row of User Control).

    Admin only lets someone manage accounts; their module roles are whatever the row says.
    """
    user = User.query.filter_by(email=user_email).first_or_404()
    was_admin = is_admin(user)
    make_admin = request.form.get('app_admin') == 'on'

    if user.user_id == current_user.user_id and was_admin and not make_admin:
        flash("You can't remove your own admin access. Ask another admin to do it.", 'danger')
        return redirect(url_for('admin.user_control'))

    plm_role = request.form.get('role_plm', '')
    roles = {
        PLM: {plm_role} if plm_role else set(),
        FILLKILL: set(request.form.getlist('role_fillkill')),
    }
    problem = validate_roles(admin=make_admin, roles=roles)
    if problem:
        flash(f"Access for {user.email} not saved: {problem}", 'danger')
        return redirect(url_for('admin.user_control'))

    apply_access(user, admin=make_admin, roles=roles, granted_by=current_user.email)
    db.session.commit()

    flash(f"Access for {user.email}: {role_summary(user)}.", 'success')
    return redirect(url_for('admin.user_control'))


@admin_bp.route('/delete-user/<string:user_email>', methods=['POST'])
@login_required
def delete_user(user_email):
    if not is_admin(current_user):
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=user_email).first_or_404()

    if user_email == current_user.email:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.user_control'))

    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.email} has been deleted.", 'success')
    return redirect(url_for('admin.user_control'))


@admin_bp.route('/approve-user/<string:user_email>', methods=['POST'])
@login_required
def approve_user_access(user_email):
    if not is_admin(current_user):
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('admin.user_control'))

    if not current_user.is_active:
        flash('Access denied: Your admin account is inactive.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=user_email).first_or_404()

    if user.email == current_user.email:
        flash('You cannot approve your own account.', 'danger')
        return redirect(url_for('admin.user_control'))

    if user.is_active:
        flash(f'{user.email} is already active.', 'info')
        return redirect(url_for('admin.user_control'))

    user.is_active = True
    user.approved_by = current_user.email
    user.approved_at = now_ny_naive()
    user.disabled_by = None
    user.disabled_at = None
    db.session.commit()

    try:
        send_mail(
            to_email=user.email,
            subject='Item Management Access Approved',
            body=(
                'Hello,\n\n'
                'Your Item Management account has been approved. You can now log in to access the application using the following link:\n'
                'http://ynbbstvwp03:5080/plm\n\n'
                'If you have any questions or need assistance, please contact Korgun Maral at kmaral@montefiore.\n\n'
                'Thank you.'
            )
        )
    except Exception:
        flash('Access approved, but the notification email could not be sent.', 'warning')

    if role_summary(user) == 'no access':
        flash(f'Approved access for {user.email}. They have no module roles yet; '
              'give them one in their row and save.', 'warning')
    else:
        flash(f'Approved access for {user.email}.', 'success')

    return redirect(url_for('admin.user_control'))


@admin_bp.route('/disable-user/<string:user_email>', methods=['POST'])
@login_required
def disable_user(user_email):
    if not is_admin(current_user):
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('admin.user_control'))

    if not current_user.is_active:
        flash('Access denied: Your admin account is inactive.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=user_email).first_or_404()

    if user.email == current_user.email:
        flash('You cannot disable your own account.', 'danger')
        return redirect(url_for('admin.user_control'))

    if not user.is_active:
        flash(f'{user.email} is already inactive.', 'info')
        return redirect(url_for('admin.user_control'))

    user.is_active = False
    user.disabled_by = current_user.email
    user.disabled_at = now_ny_naive()
    db.session.commit()

    flash(f'Disabled access for {user.email}.', 'success')
    return redirect(url_for('admin.user_control'))
