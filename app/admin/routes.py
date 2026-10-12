from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from ..models.auth import User, UserModuleRole
from ..models import now_ny_naive
from ..utility.msgraph import send_mail
from ..utility.access import (
    FILLKILL,
    FILLKILL_ROLES,
    ROLE_LABELS,
    fillkill_roles,
    role_conflict,
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

    view_args = request.view_args or {}

    # Allow the current user to stay logged in even if their role changes
    if current_user.user_role != 'admin':
        if current_user.email != view_args.get('user_email'):
            flash('Access denied: Admins only.', 'danger')
            return redirect(url_for('auth.login'))

def _set_fillkill_roles(user, roles, granted_by):
    """Replace the user's Fill/Kill roles with ``roles`` (no commit)."""
    wanted = set(roles)
    for row in list(user.module_roles):
        if row.module == FILLKILL and row.role not in wanted:
            user.module_roles.remove(row)
    held = fillkill_roles(user)
    for role in FILLKILL_ROLES:
        if role in wanted and role not in held:
            user.module_roles.append(UserModuleRole(
                module=FILLKILL, role=role, granted_by=granted_by, granted_at=now_ny_naive(),
            ))


def _role_summary(roles):
    labels = [ROLE_LABELS[code] for code in FILLKILL_ROLES if code in roles]
    return ', '.join(labels) if labels else 'none'


@admin_bp.route('/user-control')
@login_required
def user_control():
    users = User.query.all()
    return render_template(
        'admin/user_control.html',
        users=users,
        fillkill_role_choices=[(code, ROLE_LABELS[code]) for code in FILLKILL_ROLES],
        fillkill_roles_by_user={u.user_id: fillkill_roles(u) for u in users},
    )

@admin_bp.route('/update-user-role/<string:user_email>', methods=['POST'])
@login_required
def update_user_role(user_email):
    if current_user.user_role != 'admin':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('admin.user_control'))

    user = User.query.filter_by(email=user_email).first_or_404()
    new_role = request.form.get('user_role')
    if new_role in ['admin', 'user', 'view-only']:
        was_admin = user.user_role == 'admin'
        if was_admin and new_role != 'admin':
            conflict = role_conflict(fillkill_roles(user), admin=False)
            if conflict:
                flash(
                    f"{user.email} still holds both B (Nursing) and C (Materials manager) in Fill/Kill. "
                    "Remove one of them before changing their role from Admin.",
                    'danger',
                )
                return redirect(url_for('admin.user_control'))
        user.user_role = new_role
        if new_role == 'admin' and not was_admin:
            # Admins start with every Fill/Kill role and can switch any off.
            _set_fillkill_roles(user, FILLKILL_ROLES, current_user.email)
        db.session.commit()
        flash(f"Updated role for {user.email} to {new_role}.", 'success')
        # Prevent kicking out the current user by skipping redirect to login
        if user_email == current_user.email:
            print(user_email, current_user.email)
            return redirect(url_for('admin.user_control'))
    else:
        flash('Invalid role selected.', 'danger')

    return redirect(url_for('admin.user_control'))

@admin_bp.route('/update-fillkill-roles/<string:user_email>', methods=['POST'])
@login_required
def update_fillkill_roles(user_email):
    if current_user.user_role != 'admin':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('admin.user_control'))

    user = User.query.filter_by(email=user_email).first_or_404()
    requested = request.form.getlist('fillkill_roles')
    unknown = [r for r in requested if r not in FILLKILL_ROLES]
    if unknown:
        flash('Invalid Fill/Kill role selected.', 'danger')
        return redirect(url_for('admin.user_control'))

    conflict = role_conflict(requested, admin=user.user_role == 'admin')
    if conflict:
        flash(f"Fill/Kill roles for {user.email} not saved: {conflict}", 'danger')
        return redirect(url_for('admin.user_control'))

    _set_fillkill_roles(user, requested, current_user.email)
    db.session.commit()
    flash(f"Fill/Kill roles for {user.email}: {_role_summary(set(requested))}.", 'success')
    return redirect(url_for('admin.user_control'))


@admin_bp.route('/delete-user/<string:user_email>', methods=['POST'])
@login_required
def delete_user(user_email):
    if current_user.user_role != 'admin':
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
    if current_user.user_role != 'admin':
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

    flash(f'Approved access for {user.email}.', 'success')

    return redirect(url_for('admin.user_control'))


@admin_bp.route('/disable-user/<string:user_email>', methods=['POST'])
@login_required
def disable_user(user_email):
    if current_user.user_role != 'admin':
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
