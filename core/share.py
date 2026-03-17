import os
import time
import uuid
import secrets
import mimetypes

from flask import (Blueprint, request, session, jsonify,
                   url_for, send_file, render_template, current_app)

from .extensions import db
from .models import User, SharedFile, FileShare, Folder, FolderShare
from .utils import login_required, log_action

share_bp = Blueprint('share', __name__)


@share_bp.route('/api/share/link/<file_id>', methods=['POST'])
@login_required
def share_link(file_id):
    file_info = SharedFile.query.filter_by(id=file_id, user_id=session['user_id'], is_deleted=False).first()
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
    file_info = SharedFile.query.filter_by(id=file_id, user_id=session['user_id'], is_deleted=False).first()
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


@share_bp.route('/api/share/folder/link/<folder_id>', methods=['POST'])
@login_required
def share_folder_link(folder_id):
    folder = Folder.query.filter_by(id=folder_id, user_id=session['user_id']).first()
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    token = secrets.token_urlsafe(32)
    share = FolderShare(
        id=str(uuid.uuid4()),
        folder_id=folder.id,
        shared_by=session['user_id'],
        share_token=token,
        expires_at=time.time() + 7 * 24 * 3600,
    )
    db.session.add(share)
    log_action('folder_share_link', folder.name)
    db.session.commit()

    link = url_for('share.access_share', token=token, _external=True)
    return jsonify({'success': True, 'share_link': link})


@share_bp.route('/api/share/folder/user/<folder_id>', methods=['POST'])
@login_required
def share_folder_with_user(folder_id):
    folder = Folder.query.filter_by(id=folder_id, user_id=session['user_id']).first()
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    data = request.get_json() or {}
    target = User.query.filter_by(username=(data.get('username') or '').strip()).first()
    if not target:
        return jsonify({'error': 'User not found'}), 404
    if target.id == session['user_id']:
        return jsonify({'error': 'Cannot share with yourself'}), 400

    already = FolderShare.query.filter_by(
        folder_id=folder.id, shared_with=target.id, is_active=True
    ).first()
    if already:
        return jsonify({'error': f'Already shared with {target.username}'}), 400

    share = FolderShare(
        id=str(uuid.uuid4()),
        folder_id=folder.id,
        shared_by=session['user_id'],
        shared_with=target.id,
        share_token=secrets.token_urlsafe(32),
    )
    db.session.add(share)
    log_action('share_user', folder.name)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Folder shared with {target.username}'})


@share_bp.route('/share/<token>')
def access_share(token):
    file_share = FileShare.query.filter_by(share_token=token, is_active=True).first()
    if file_share:
        if file_share.expires_at and time.time() > file_share.expires_at:
            file_share.is_active = False
            db.session.commit()
            return render_template('error.html', message='This share link has expired.'), 410

        f = file_share.file
        if not f or f.is_deleted:
            return render_template('error.html', message='File is no longer available.'), 404

        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f.user_id, f.stored_name)
        if not os.path.exists(file_path):
            return render_template('error.html', message='File no longer exists on the server.'), 404

        log_action('share_access', f.original_name, username_override=f.owner.username if f.owner else None)
        db.session.commit()
        return send_file(file_path, as_attachment=True, download_name=f.original_name)

    folder_share = FolderShare.query.filter_by(share_token=token, is_active=True).first()
    if folder_share:
        if folder_share.expires_at and time.time() > folder_share.expires_at:
            folder_share.is_active = False
            db.session.commit()
            return render_template('error.html', message='This folder share link has expired.'), 410

        folder = folder_share.folder
        if not folder:
            return render_template('error.html', message='Folder no longer exists.'), 404

        files = SharedFile.query.filter_by(folder_id=folder.id, is_deleted=False).order_by(SharedFile.uploaded_at.desc()).all()
        log_action('folder_share_access', folder.name, username_override=folder.owner.username if folder.owner else None)
        db.session.commit()
        return render_template('folder_share.html', folder=folder, files=files, token=token)

    return render_template('error.html', message='Invalid or revoked share link.'), 404


@share_bp.route('/share/folder/<token>/download/<file_id>')
def download_from_folder_share(token, file_id):
    share = FolderShare.query.filter_by(share_token=token, is_active=True).first()
    if not share:
        return render_template('error.html', message='Invalid or revoked folder share link.'), 404
    if share.expires_at and time.time() > share.expires_at:
        share.is_active = False
        db.session.commit()
        return render_template('error.html', message='This folder share link has expired.'), 410

    file_info = SharedFile.query.filter_by(id=file_id, folder_id=share.folder_id, is_deleted=False).first()
    if not file_info:
        return render_template('error.html', message='File not found in this shared folder.'), 404

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_info.user_id, file_info.stored_name)
    if not os.path.exists(file_path):
        return render_template('error.html', message='File no longer exists on the server.'), 404
    return send_file(file_path, as_attachment=True, download_name=file_info.original_name)


@share_bp.route('/share/folder/<token>/view/<file_id>')
def view_from_folder_share(token, file_id):
    share = FolderShare.query.filter_by(share_token=token, is_active=True).first()
    if not share:
        return render_template('error.html', message='Invalid or revoked folder share link.'), 404
    if share.expires_at and time.time() > share.expires_at:
        share.is_active = False
        db.session.commit()
        return render_template('error.html', message='This folder share link has expired.'), 410

    file_info = SharedFile.query.filter_by(id=file_id, folder_id=share.folder_id, is_deleted=False).first()
    if not file_info:
        return render_template('error.html', message='File not found in this shared folder.'), 404

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_info.user_id, file_info.stored_name)
    if not os.path.exists(file_path):
        return render_template('error.html', message='File no longer exists on the server.'), 404

    guessed, _ = mimetypes.guess_type(file_info.original_name)
    previewable = bool(guessed and (
        guessed.startswith('text/')
        or guessed.startswith('image/')
        or guessed.startswith('audio/')
        or guessed.startswith('video/')
        or guessed in {'application/pdf'}
    ))
    if not previewable:
        return render_template('error.html', message='Preview is not supported for this file type.'), 415
    return send_file(file_path, as_attachment=False, download_name=file_info.original_name, mimetype=guessed)


@share_bp.route('/api/share/file/revoke/<share_id>', methods=['DELETE'])
@login_required
def revoke_file_share(share_id):
    share = db.session.get(FileShare, share_id)
    if not share:
        return jsonify({'error': 'Share not found'}), 404
    if share.shared_by != session['user_id']:
        return jsonify({'error': 'Not allowed'}), 403
    share.is_active = False
    log_action('share_revoke', share.file.original_name if share.file else 'file_share')
    db.session.commit()
    return jsonify({'success': True})


@share_bp.route('/api/share/folder/revoke/<share_id>', methods=['DELETE'])
@login_required
def revoke_folder_share(share_id):
    share = db.session.get(FolderShare, share_id)
    if not share:
        return jsonify({'error': 'Share not found'}), 404
    if share.shared_by != session['user_id']:
        return jsonify({'error': 'Not allowed'}), 403
    share.is_active = False
    log_action('share_revoke', share.folder.name if share.folder else 'folder_share')
    db.session.commit()
    return jsonify({'success': True})
