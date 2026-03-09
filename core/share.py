import os
import time
import uuid
import secrets

from flask import (Blueprint, request, session, jsonify,
                   url_for, send_file, render_template, current_app)

from .extensions import db
from .models import User, SharedFile, FileShare
from .utils import login_required, log_action

share_bp = Blueprint('share', __name__)


@share_bp.route('/api/share/link/<file_id>', methods=['POST'])
@login_required
def share_link(file_id):
    file_info = SharedFile.query.filter_by(id=file_id, user_id=session['user_id']).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404

    token = secrets.token_urlsafe(32)
    share = FileShare(
        id          = str(uuid.uuid4()),
        file_id     = file_info.id,
        shared_by   = session['user_id'],
        share_token = token,
        expires_at  = time.time() + 7 * 24 * 3600,
    )
    db.session.add(share)
    log_action('share_link', file_info.original_name)
    db.session.commit()

    link = url_for('share.access_share', token=token, _external=True)
    return jsonify({'success': True, 'share_link': link})


@share_bp.route('/api/share/user/<file_id>', methods=['POST'])
@login_required
def share_with_user(file_id):
    file_info = SharedFile.query.filter_by(id=file_id, user_id=session['user_id']).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404

    data   = request.get_json()
    target = User.query.filter_by(username=data.get('username', '').strip()).first()
    if not target:
        return jsonify({'error': 'User not found'}), 404
    if target.id == session['user_id']:
        return jsonify({'error': 'Cannot share with yourself'}), 400

    already = FileShare.query.filter_by(
        file_id=file_info.id, shared_with=target.id, is_active=True
    ).first()
    if already:
        return jsonify({'error': f'Already shared with {target.username}'}), 400

    share = FileShare(
        id          = str(uuid.uuid4()),
        file_id     = file_info.id,
        shared_by   = session['user_id'],
        shared_with = target.id,
        share_token = secrets.token_urlsafe(32),
    )
    db.session.add(share)
    log_action('share_user', file_info.original_name)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Shared with {target.username}'})


@share_bp.route('/share/<token>')
def access_share(token):
    share = FileShare.query.filter_by(share_token=token, is_active=True).first()
    if not share:
        return render_template('error.html', message='Invalid or revoked share link.'), 404

    if share.expires_at and time.time() > share.expires_at:
        share.is_active = False
        db.session.commit()
        return render_template('error.html', message='This share link has expired.'), 410

    f         = share.file
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f.user_id, f.stored_name)
    if not os.path.exists(file_path):
        return render_template('error.html', message='File no longer exists on the server.'), 404

    return send_file(file_path, as_attachment=True, download_name=f.original_name)
