from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from ..models.auth import User
from .. import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.before_request
def restrict_to_admin():
    if not current_user.is_authenticated or current_user.user_role != 'admin':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('auth.login'))

@admin_bp.route('/user-control')
@login_required
def user_control():
    users = User.query.all()
    return render_template('admin/user_control.html', users=users)

@admin_bp.route('/update-user-role/<int:user_id>', methods=['POST'])
@login_required
def update_user_role(user_id):
    if current_user.user_role != 'admin':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.get_or_404(user_id)
    new_role = request.form.get('user_role')
    if new_role in ['admin', 'user', 'view-only']:
        user.user_role = new_role
        db.session.commit()
        flash(f"Updated role for {user.email} to {new_role}.", 'success')
        if user_id == current_user.id:
            return redirect(url_for('main.index'))
    else:
        flash('Invalid role selected.', 'danger')

    return redirect(url_for('admin.user_control'))

@admin_bp.route('/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.user_role != 'admin':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.get_or_404(user_id)
    confirm_email = request.form.get('confirm_email')

    if confirm_email != user.email:
        flash('Email confirmation does not match.', 'danger')
        return redirect(url_for('admin.user_control'))

    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.email} has been deleted.", 'success')
    return redirect(url_for('admin.user_control'))
