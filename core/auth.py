import os
import time
import uuid
from datetime import datetime

from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, jsonify, current_app, send_from_directory)
from sqlalchemy import or_, func
from werkzeug.utils import secure_filename

from .extensions import db
from .models import User, ActivityLog
from .utils import login_required, log_action

auth_bp = Blueprint('auth', __name__)
_ALLOWED_PROFILE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
_LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_LOGIN_FAILURE_LIMIT = 8
_ALLOWED_DEPARTMENTS = {
    'EEE', 'CSE', 'ETE', 'ECE', 'CE', 'URP', 'Arch',
    'BECM', 'ME', 'IPE', 'CME', 'MTE', 'MSE', 'ChE'
}


def _is_login_rate_limited(identifier, ip_address):
    now = time.time()
    cutoff = now - _LOGIN_FAILURE_WINDOW_SECONDS
    clauses = [ActivityLog.ip_address == ip_address] if ip_address else []
    if identifier:
        clauses.append(func.lower(ActivityLog.username) == identifier.lower())
    if not clauses:
        return False
    failures = ActivityLog.query.filter(
        ActivityLog.action == 'login_failure',
        ActivityLog.timestamp >= cutoff,
        or_(*clauses),
    ).count()
    return failures >= _LOGIN_FAILURE_LIMIT


@auth_bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if 'user_id' in session:
        return redirect(url_for('files.index'))

    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not identifier or not password:
            return render_template('login.html', error='Username/email and password are required')

        if _is_login_rate_limited(identifier, request.remote_addr):
            log_action('login_rate_limited', outcome='FAILURE', username_override=identifier)
            db.session.commit()
            return render_template(
                'login.html',
                error='Too many failed login attempts. Please wait 15 minutes and try again.'
            ), 429

        user = User.query.filter(
            or_(User.username == identifier, User.email == identifier.lower())
        ).first()
        if not user or not user.check_password(password):
            log_action('login_failure', outcome='FAILURE', username_override=identifier)
            db.session.commit()
            return render_template('login.html', error='Invalid username/email or password')

        session.permanent   = True
        session['user_id']  = user.id
        session['username'] = user.username
        log_action('login')
        db.session.commit()
        if user.is_admin:
            return redirect(url_for('admin.admin_page'))
        return redirect(url_for('files.index'))

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register_page():
    if 'user_id' in session:
        return redirect(url_for('files.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        if not username or not email or not password or not confirm:
            return render_template('register.html', error='All fields are required')

        if len(username) < 3 or len(username) > 32:
            return render_template('register.html', error='Username must be 3-32 characters')

        if not username.replace('_', '').replace('-', '').isalnum():
            return render_template('register.html',
                                   error='Username may only contain letters, numbers, hyphens, and underscores')

        local_part, _, domain = email.partition('@')
        if not local_part or domain != 'student.ruet.ac.bd':
            return render_template('register.html',
                                   error='Only RUET student emails are allowed (yourname@student.ruet.ac.bd)')
        if not local_part.replace('.', '').replace('-', '').replace('_', '').isalnum():
            return render_template('register.html', error='Invalid email address')

        if len(password) < 6:
            return render_template('register.html', error='Password must be at least 6 characters')

        if password != confirm:
            return render_template('register.html', error='Passwords do not match')

        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Username already taken')

        if User.query.filter_by(email=email).first():
            return render_template('register.html',
                                   error='An account with this email already exists')

        user = User(id=str(uuid.uuid4()), username=username, email=email, created_at=time.time())
        user.set_password(password)
        db.session.add(user)
        log_action('register', username_override=username)
        db.session.commit()

        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(os.path.join(upload_folder, user.id), exist_ok=True)
        return redirect(url_for('auth.login_page'))

    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    if 'user_id' in session:
        log_action('logout')
        db.session.commit()
    session.clear()
    return redirect(url_for('auth.login_page'))


@auth_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def api_logout():
    log_action('logout')
    db.session.commit()
    session.clear()
    return jsonify({'success': True})


@auth_bp.route('/api/auth/me', methods=['GET'])
@login_required
def api_me():
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify({
        'id':            user.id,
        'username':      user.username,
        'email':         user.email,
        'full_name':     user.full_name,
        'dob':           user.dob,
        'academic_series': user.academic_series,
        'department':    user.department,
        'profile_image_url': url_for('auth.profile_image', filename=user.profile_image) if user.profile_image else None,
        'is_admin':      user.is_admin,
        'storage_limit': user.storage_limit,
        'storage_used':  user.storage_used or 0,
    })


@auth_bp.route('/profile')
@login_required
def profile_page():
    return render_template('profile.html', username=session.get('username'))


@auth_bp.route('/api/profile', methods=['GET'])
@login_required
def get_profile():
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify({
        'username': user.username,
        'email': user.email,
        'full_name': user.full_name or '',
        'dob': user.dob or '',
        'academic_series': user.academic_series or '',
        'department': user.department or '',
        'profile_image_url': url_for('auth.profile_image', filename=user.profile_image) if user.profile_image else None,
    })


@auth_bp.route('/api/profile', methods=['POST'])
@login_required
def update_profile():
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401

    full_name = (request.form.get('full_name') or '').strip()
    dob = (request.form.get('dob') or '').strip()
    academic_series = (request.form.get('academic_series') or '').strip()
    department = (request.form.get('department') or '').strip()
    remove_profile_image = (request.form.get('remove_profile_image') or '').strip() == '1'

    if len(full_name) > 120 or len(academic_series) > 40 or len(department) > 80:
        return jsonify({'error': 'One or more fields are too long'}), 400

    if department and department not in _ALLOWED_DEPARTMENTS:
        return jsonify({'error': 'Invalid department selection'}), 400

    if academic_series:
        if not academic_series.isdigit():
            return jsonify({'error': 'Academic series must be an integer'}), 400
        series_num = int(academic_series)
        if not (0 <= series_num <= 99):
            return jsonify({'error': 'Academic series must be between 0 and 99'}), 400

        now_year = datetime.utcnow().year
        current_suffix = now_year % 100
        full_year = 2000 + series_num if series_num <= current_suffix else 1900 + series_num
        if full_year < 1964 or full_year > now_year:
            return jsonify({'error': 'Academic series must be within 1964 to present'}), 400
        academic_series = str(series_num)

    user.full_name = full_name or None
    user.dob = dob or None
    user.academic_series = academic_series or None
    user.department = department or None

    image = request.files.get('profile_image')
    profile_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'profile_images')

    if remove_profile_image and user.profile_image:
        old_path = os.path.join(profile_dir, user.profile_image)
        if os.path.exists(old_path):
            os.remove(old_path)
        user.profile_image = None

    if image and image.filename:
        ext = os.path.splitext(image.filename.lower())[1]
        if ext not in _ALLOWED_PROFILE_EXTS:
            return jsonify({'error': 'Invalid image type'}), 400
        if image.mimetype and not image.mimetype.startswith('image/'):
            return jsonify({'error': 'Invalid image file'}), 400

        os.makedirs(profile_dir, exist_ok=True)
        new_name = f"{user.id}_{uuid.uuid4().hex[:10]}{ext}"
        new_path = os.path.join(profile_dir, secure_filename(new_name))
        image.save(new_path)

        if user.profile_image:
            old_path = os.path.join(profile_dir, user.profile_image)
            if os.path.exists(old_path):
                os.remove(old_path)
        user.profile_image = os.path.basename(new_path)

    log_action('profile_update', user.username)
    db.session.commit()
    return jsonify({'success': True})


@auth_bp.route('/profile-image/<filename>')
@login_required
def profile_image(filename):
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    if not user.profile_image or filename != user.profile_image:
        return jsonify({'error': 'Access denied'}), 403
    profile_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'profile_images')
    return send_from_directory(profile_dir, filename)
