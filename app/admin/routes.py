from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from ..models.auth import User
from .. import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.before_request
def restrict_to_admin():
    if not current_user.is_authenticated:
        flash('Access denied: Please log in.', 'danger')
        return redirect(url_for('auth.login'))

    # Allow the current user to stay logged in even if their role changes
    if current_user.user_role != 'admin':
        if current_user.email != request.view_args.get('user_email', None):
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
