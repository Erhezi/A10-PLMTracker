from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from ..models.auth import User
from ..models import now_ny_naive
from ..utility.msgraph import send_mail
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

@admin_bp.route('/user-control')
@login_required
def user_control():
    users = User.query.all()
    return render_template('admin/user_control.html', users=users)

@admin_bp.route('/update-user-role/<string:user_email>', methods=['POST'])
@login_required
def update_user_role(user_email):
    if current_user.user_role != 'admin':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('admin.user_control'))

    user = User.query.filter_by(email=user_email).first_or_404()
    new_role = request.form.get('user_role')
    if new_role in ['admin', 'user', 'view-only']:
        user.user_role = new_role
        db.session.commit()
        flash(f"Updated role for {user.email} to {new_role}.", 'success')
        # Prevent kicking out the current user by skipping redirect to login
        if user_email == current_user.email:
            print(user_email, current_user.email)
            return redirect(url_for('admin.user_control'))
    else:
        flash('Invalid role selected.', 'danger')

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
            subject='PLM Tracker Access Approved',
            body=(
                'Hello,\n\n'
                'Your PLM Tracker account has been approved. You can now log in to access the application using the following link:\n'
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
