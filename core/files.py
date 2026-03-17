import os
import time
import uuid
import mimetypes
from datetime import datetime

from flask import (Blueprint, render_template, request, session,
                   jsonify, send_file, current_app, url_for)
from werkzeug.utils import secure_filename
from sqlalchemy import func

from .extensions import db
from .models import User, SharedFile, FileShare, Folder, FolderShare
from .utils import login_required, log_action, format_file_size, validate_file

files_bp = Blueprint('files', __name__)


@files_bp.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'))


@files_bp.route('/api/files', methods=['GET'])
@login_required
def get_files():
    user_id = session['user_id']

    own_files = SharedFile.query.filter_by(user_id=user_id, is_deleted=False).all()
    direct_share_links = FileShare.query.filter_by(shared_with=user_id, is_active=True).all()
    shared_files = [s.file for s in direct_share_links if s.file and not s.file.is_deleted]
    direct_shared_file_ids = {s.file_id for s in direct_share_links}

    folder_share_links = FolderShare.query.filter_by(shared_with=user_id, is_active=True).all()
    shared_folder_ids = [s.folder_id for s in folder_share_links]
    shared_folder_files = []
    if shared_folder_ids:
        shared_folder_files = SharedFile.query.filter(
            SharedFile.folder_id.in_(shared_folder_ids),
            SharedFile.is_deleted == False
        ).all()
    folder_shared_file_ids = {f.id for f in shared_folder_files}

    seen, all_files = set(), []
    for f in own_files + shared_files + shared_folder_files:
        if f.id not in seen:
            seen.add(f.id)
            all_files.append(f)
    all_files.sort(key=lambda x: x.uploaded_at, reverse=True)

    return jsonify([{
        'id':             f.id,
        'original_name':  f.original_name,
        'stored_name':    f.stored_name,
        'size':           f.size,
        'size_formatted': format_file_size(f.size),
        'uploaded_at':    f.uploaded_at,
        'date':           datetime.fromtimestamp(f.uploaded_at).strftime('%Y-%m-%d %H:%M'),
        'owner':          f.owner.username if f.user_id != user_id else '',
        'is_owned':       f.user_id == user_id,
        'shared_via_folder': (
            f.id in folder_shared_file_ids
            and f.id not in direct_shared_file_ids
            and f.user_id != user_id
        ),
        'folder_id':      f.folder_id,
        'folder_name':    f.folder.name if f.folder else '',
    } for f in all_files])


@files_bp.route('/api/folders', methods=['GET'])
@login_required
def get_folders():
    user_id = session['user_id']
    folders = Folder.query.filter_by(user_id=user_id, is_deleted=False).order_by(Folder.created_at.asc()).all()
    return jsonify([{
        'id':         folder.id,
        'name':       folder.name,
        'created_at': folder.created_at,
        'file_count': SharedFile.query.filter_by(
            user_id=user_id, folder_id=folder.id, is_deleted=False
        ).count(),
    } for folder in folders])


@files_bp.route('/api/folders/shared', methods=['GET'])
@login_required
def get_shared_folders():
    user_id = session['user_id']
    shares = FolderShare.query.filter_by(shared_with=user_id, is_active=True).order_by(FolderShare.created_at.desc()).all()
    seen = set()
    items = []
    for s in shares:
        folder = s.folder
        if not folder or folder.is_deleted or folder.id in seen:
            continue
        seen.add(folder.id)
        items.append({
            'id': folder.id,
            'name': folder.name,
            'created_at': folder.created_at,
            'date': datetime.fromtimestamp(folder.created_at).strftime('%Y-%m-%d %H:%M'),
            'file_count': SharedFile.query.filter_by(folder_id=folder.id, is_deleted=False).count(),
            'owner': folder.owner.username if folder.owner else '—',
            'is_owned': False,
        })
    return jsonify(items)


@files_bp.route('/api/folders', methods=['POST'])
@login_required
def create_folder():
    user_id = session['user_id']
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Folder name is required'}), 400
    if len(name) > 120:
        return jsonify({'error': 'Folder name is too long'}), 400

    existing = Folder.query.filter(
        Folder.user_id == user_id,
        func.lower(Folder.name) == name.lower(),
        Folder.is_deleted == False
    ).first()
    if existing:
        return jsonify({'error': 'Folder already exists'}), 400

    folder = Folder(id=str(uuid.uuid4()), user_id=user_id, name=name, created_at=time.time())
    db.session.add(folder)
    log_action('folder_create', name)
    db.session.commit()
    return jsonify({'success': True, 'folder': {'id': folder.id, 'name': folder.name}})


@files_bp.route('/api/folders/<folder_id>/open', methods=['POST'])
@login_required
def open_folder(folder_id):
    user_id = session['user_id']
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id, is_deleted=False).first()
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404
    log_action('folder_open', folder.name)
    db.session.commit()
    return jsonify({'success': True})


@files_bp.route('/api/folders/<folder_id>', methods=['DELETE'])
@login_required
def delete_folder(folder_id):
    user_id = session['user_id']
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id, is_deleted=False).first()
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    now = time.time()
    files = SharedFile.query.filter_by(user_id=user_id, folder_id=folder.id, is_deleted=False).all()
    for f in files:
        f.is_deleted = True
        f.deleted_at = now

    folder_name = folder.name
    folder.is_deleted = True
    folder.deleted_at = now
    log_action('folder_delete', folder_name)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Folder moved to trash'})


@files_bp.route('/api/folders/<folder_id>/rename', methods=['POST'])
@login_required
def rename_folder(folder_id):
    user_id = session['user_id']
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id, is_deleted=False).first()
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    data = request.get_json() or {}
    new_name = (data.get('name') or '').strip()
    if not new_name:
        return jsonify({'error': 'Folder name is required'}), 400
    if len(new_name) > 120:
        return jsonify({'error': 'Folder name is too long'}), 400

    existing = Folder.query.filter(
        Folder.user_id == user_id,
        func.lower(Folder.name) == new_name.lower(),
        Folder.id != folder.id,
        Folder.is_deleted == False
    ).first()
    if existing:
        return jsonify({'error': 'Folder already exists'}), 400

    folder.name = new_name
    log_action('folder_rename', new_name)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Folder renamed'})


@files_bp.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400

    user_id         = session['user_id']
    user            = db.session.get(User, user_id)
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    upload_folder   = current_app.config['UPLOAD_FOLDER']
    user_upload_dir = os.path.join(upload_folder, user_id)
    os.makedirs(user_upload_dir, exist_ok=True)

    uploaded, rejected = [], []
    projected_usage = user.storage_used or 0
    storage_limit = user.storage_limit or 0
    target_folder_id = (request.form.get('folder_id') or '').strip() or None
    if target_folder_id:
        folder = Folder.query.filter_by(id=target_folder_id, user_id=user_id, is_deleted=False).first()
        if not folder:
            return jsonify({'error': 'Folder not found'}), 404

    for file in request.files.getlist('files'):
        if not file or not file.filename:
            continue

        allowed, _ = validate_file(file.filename, file.stream)
        if not allowed:
            rejected.append(file.filename)
            continue

        stream = file.stream
        start_pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        incoming_size = stream.tell()
        stream.seek(start_pos)
        if incoming_size <= 0:
            rejected.append(file.filename)
            continue
        if storage_limit > 0 and projected_usage + incoming_size > storage_limit:
            rejected.append(file.filename)
            continue

        original_name = secure_filename(file.filename)
        base, ext     = os.path.splitext(original_name)
        stored_name   = f"{base}_{str(uuid.uuid4())[:8]}{ext}"
        file_path     = os.path.join(user_upload_dir, stored_name)
        file.save(file_path)
        file_size = os.path.getsize(file_path)

        record = SharedFile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            original_name=original_name,
            stored_name=stored_name,
            size=file_size,
            folder_id=target_folder_id,
            uploaded_at=time.time(),
        )
        db.session.add(record)
        projected_usage += file_size
        user.storage_used = projected_usage
        log_action('upload', original_name)

        uploaded.append({
            'id':             record.id,
            'original_name':  original_name,
            'stored_name':    stored_name,
            'size':           file_size,
            'size_formatted': format_file_size(file_size),
            'uploaded_at':    record.uploaded_at,
            'date':           'just now',
            'owner':          '',
            'folder_id':      record.folder_id,
            'folder_name':    folder.name if target_folder_id else '',
        })

    db.session.commit()

    if not uploaded and rejected:
        return jsonify({
            'error': 'All files were rejected. Executable binaries and server-side scripts are not allowed.'
        }), 400

    response = {'success': True, 'files': uploaded, 'message': f'Uploaded {len(uploaded)} file(s)'}
    if rejected:
        response['warning'] = (
            f'Rejected {len(rejected)} file(s) (executable or server-side script): '
            + ', '.join(rejected)
        )
    return jsonify(response)


@files_bp.route('/api/download/<file_id>')
@login_required
def download_file(file_id):
    user_id   = session['user_id']
    file_info = SharedFile.query.filter_by(stored_name=file_id).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    if file_info.is_deleted:
        return jsonify({'error': 'File is in trash'}), 404

    owns   = file_info.user_id == user_id
    shared = FileShare.query.filter_by(
        file_id=file_info.id, shared_with=user_id, is_active=True
    ).first()
    folder_shared = False
    if file_info.folder_id:
        folder_shared = FolderShare.query.filter_by(
            folder_id=file_info.folder_id, shared_with=user_id, is_active=True
        ).first() is not None
    if not owns and not shared and not folder_shared:
        return jsonify({'error': 'Access denied'}), 403

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_info.user_id, file_id)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found on server'}), 404

    log_action('download', file_info.original_name)
    db.session.commit()
    return send_file(file_path, as_attachment=True, download_name=file_info.original_name)


@files_bp.route('/api/view/<file_id>')
@login_required
def view_file(file_id):
    user_id = session['user_id']
    file_info = SharedFile.query.filter_by(stored_name=file_id).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    if file_info.is_deleted:
        return jsonify({'error': 'File is in trash'}), 404

    owns = file_info.user_id == user_id
    shared = FileShare.query.filter_by(
        file_id=file_info.id, shared_with=user_id, is_active=True
    ).first()
    folder_shared = False
    if file_info.folder_id:
        folder_shared = FolderShare.query.filter_by(
            folder_id=file_info.folder_id, shared_with=user_id, is_active=True
        ).first() is not None
    if not owns and not shared and not folder_shared:
        return jsonify({'error': 'Access denied'}), 403

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_info.user_id, file_id)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found on server'}), 404

    guessed, _ = mimetypes.guess_type(file_info.original_name)
    previewable = bool(guessed and (
        guessed.startswith('text/')
        or guessed.startswith('image/')
        or guessed.startswith('audio/')
        or guessed.startswith('video/')
        or guessed in {'application/pdf'}
    ))
    if not previewable:
        return jsonify({'error': 'Preview not supported for this file type'}), 415

    log_action('preview', file_info.original_name)
    db.session.commit()
    return send_file(file_path, as_attachment=False, download_name=file_info.original_name, mimetype=guessed)


@files_bp.route('/api/delete/<file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id):
    user_id   = session['user_id']
    file_info = SharedFile.query.filter_by(id=file_id, user_id=user_id, is_deleted=False).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404

    file_info.is_deleted = True
    file_info.deleted_at = time.time()
    log_action('delete', file_info.original_name)
    db.session.commit()
    return jsonify({'success': True, 'message': 'File moved to trash'})


@files_bp.route('/api/files/<file_id>/rename', methods=['POST'])
@login_required
def rename_file(file_id):
    user_id = session['user_id']
    file_info = SharedFile.query.filter_by(id=file_id, user_id=user_id, is_deleted=False).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404

    data = request.get_json() or {}
    raw_name = (data.get('name') or '').strip()
    if not raw_name:
        return jsonify({'error': 'File name is required'}), 400
    if len(raw_name) > 255:
        return jsonify({'error': 'File name is too long'}), 400

    cleaned = secure_filename(raw_name)
    if not cleaned:
        return jsonify({'error': 'Invalid file name'}), 400

    file_info.original_name = cleaned
    log_action('file_rename', cleaned)
    db.session.commit()
    return jsonify({'success': True, 'message': 'File renamed'})


@files_bp.route('/api/files/<file_id>/info', methods=['GET'])
@login_required
def file_info(file_id):
    user_id = session['user_id']
    file_info = SharedFile.query.filter_by(id=file_id, is_deleted=False).first()
    if not file_info:
        return jsonify({'error': 'File not found'}), 404

    owns = file_info.user_id == user_id
    direct_share = FileShare.query.filter_by(file_id=file_info.id, shared_with=user_id, is_active=True).first()
    folder_share = None
    if file_info.folder_id:
        folder_share = FolderShare.query.filter_by(
            folder_id=file_info.folder_id, shared_with=user_id, is_active=True
        ).first()
    if not owns and not direct_share and not folder_share:
        return jsonify({'error': 'Access denied'}), 403

    share_items = []
    if owns:
        shares = FileShare.query.filter_by(file_id=file_info.id, is_active=True).order_by(FileShare.created_at.desc()).all()
        for s in shares:
            target_user = db.session.get(User, s.shared_with) if s.shared_with else None
            share_items.append({
                'share_id': s.id,
                'scope': 'public' if not s.shared_with else 'user',
                'shared_with': target_user.username if target_user else ('Public link' if not s.shared_with else '—'),
                'created_at': datetime.fromtimestamp(s.created_at).strftime('%Y-%m-%d %H:%M'),
                'expires_at': datetime.fromtimestamp(s.expires_at).strftime('%Y-%m-%d %H:%M') if s.expires_at else '—',
                'is_active': s.is_active,
                'share_link': url_for('share.access_share', token=s.share_token, _external=True) if not s.shared_with else None,
            })

    return jsonify({
        'type': 'file',
        'id': file_info.id,
        'name': file_info.original_name,
        'size': file_info.size,
        'size_formatted': format_file_size(file_info.size),
        'uploaded_at': datetime.fromtimestamp(file_info.uploaded_at).strftime('%Y-%m-%d %H:%M'),
        'owner': file_info.owner.username if file_info.owner else '—',
        'folder_name': file_info.folder.name if file_info.folder else 'Root',
        'can_manage_shares': owns,
        'shares': share_items,
    })


@files_bp.route('/api/folders/<folder_id>/info', methods=['GET'])
@login_required
def folder_info(folder_id):
    user_id = session['user_id']
    folder = Folder.query.filter_by(id=folder_id, is_deleted=False).first()
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    owns = folder.user_id == user_id
    shared = FolderShare.query.filter_by(folder_id=folder.id, shared_with=user_id, is_active=True).first()
    if not owns and not shared:
        return jsonify({'error': 'Access denied'}), 403

    files = SharedFile.query.filter_by(folder_id=folder.id, is_deleted=False).all()
    total_size = sum(f.size for f in files)

    share_items = []
    if owns:
        shares = FolderShare.query.filter_by(folder_id=folder.id, is_active=True).order_by(FolderShare.created_at.desc()).all()
        for s in shares:
            target_user = db.session.get(User, s.shared_with) if s.shared_with else None
            share_items.append({
                'share_id': s.id,
                'scope': 'public' if not s.shared_with else 'user',
                'shared_with': target_user.username if target_user else ('Public link' if not s.shared_with else '—'),
                'created_at': datetime.fromtimestamp(s.created_at).strftime('%Y-%m-%d %H:%M'),
                'expires_at': datetime.fromtimestamp(s.expires_at).strftime('%Y-%m-%d %H:%M') if s.expires_at else '—',
                'is_active': s.is_active,
                'share_link': url_for('share.access_share', token=s.share_token, _external=True) if not s.shared_with else None,
            })

    return jsonify({
        'type': 'folder',
        'id': folder.id,
        'name': folder.name,
        'owner': folder.owner.username if folder.owner else '—',
        'created_at': datetime.fromtimestamp(folder.created_at).strftime('%Y-%m-%d %H:%M'),
        'file_count': len(files),
        'total_size': total_size,
        'total_size_formatted': format_file_size(total_size),
        'can_manage_shares': owns,
        'shares': share_items,
    })


@files_bp.route('/api/clear', methods=['POST'])
@login_required
def clear_all_files():
    user_id         = session['user_id']
    now = time.time()
    files = SharedFile.query.filter_by(user_id=user_id, is_deleted=False).all()
    for f in files:
        f.is_deleted = True
        f.deleted_at = now

    log_action('clear_all')
    db.session.commit()

    return jsonify({'success': True, 'message': 'All files moved to trash'})


@files_bp.route('/api/trash', methods=['GET'])
@login_required
def get_trash():
    user_id = session['user_id']
    trash_files = SharedFile.query.filter_by(user_id=user_id, is_deleted=True).all()
    trash_folders = Folder.query.filter_by(user_id=user_id, is_deleted=True).all()

    visible_files = []
    for f in trash_files:
        if f.folder and f.folder.user_id == user_id and f.folder.is_deleted:
            continue
        visible_files.append(f)

    items = [{
        'type':           'file',
        'id':             f.id,
        'original_name':  f.original_name,
        'stored_name':    f.stored_name,
        'size':           f.size,
        'size_formatted': format_file_size(f.size),
        'uploaded_at':    f.uploaded_at,
        'deleted_at':     f.deleted_at,
        'date':           datetime.fromtimestamp(f.deleted_at).strftime('%Y-%m-%d %H:%M') if f.deleted_at else '',
        'folder_id':      f.folder_id,
        'folder_name':    f.folder.name if f.folder else '',
    } for f in visible_files]

    items.extend([{
        'type':       'folder',
        'id':         fld.id,
        'name':       fld.name,
        'deleted_at': fld.deleted_at,
        'date':       datetime.fromtimestamp(fld.deleted_at).strftime('%Y-%m-%d %H:%M') if fld.deleted_at else '',
        'file_count': SharedFile.query.filter_by(user_id=user_id, folder_id=fld.id, is_deleted=True).count(),
    } for fld in trash_folders])

    items.sort(key=lambda x: x.get('deleted_at') or 0, reverse=True)
    return jsonify(items)


@files_bp.route('/api/trash/restore/<file_id>', methods=['POST'])
@login_required
def restore_from_trash(file_id):
    user_id = session['user_id']
    file_info = SharedFile.query.filter_by(id=file_id, user_id=user_id, is_deleted=True).first()
    if not file_info:
        return jsonify({'error': 'File not found in trash'}), 404

    file_info.is_deleted = False
    file_info.deleted_at = None
    log_action('trash_restore', file_info.original_name)
    db.session.commit()
    return jsonify({'success': True, 'message': 'File restored'})


@files_bp.route('/api/trash/folders/restore/<folder_id>', methods=['POST'])
@login_required
def restore_folder_from_trash(folder_id):
    user_id = session['user_id']
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id, is_deleted=True).first()
    if not folder:
        return jsonify({'error': 'Folder not found in trash'}), 404

    folder.is_deleted = False
    folder.deleted_at = None

    files = SharedFile.query.filter_by(user_id=user_id, folder_id=folder.id, is_deleted=True).all()
    for f in files:
        f.is_deleted = False
        f.deleted_at = None

    log_action('trash_restore', folder.name)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Folder restored'})


@files_bp.route('/api/trash/delete/<file_id>', methods=['DELETE'])
@login_required
def delete_from_trash(file_id):
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    file_info = SharedFile.query.filter_by(id=file_id, user_id=user_id, is_deleted=True).first()
    if not file_info:
        return jsonify({'error': 'File not found in trash'}), 404

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], user_id, file_info.stored_name)
    if os.path.exists(file_path):
        os.remove(file_path)

    user.storage_used = max(0, (user.storage_used or 0) - file_info.size)
    log_action('trash_delete', file_info.original_name)
    db.session.delete(file_info)
    db.session.commit()
    return jsonify({'success': True, 'message': 'File permanently deleted'})


@files_bp.route('/api/trash/folders/delete/<folder_id>', methods=['DELETE'])
@login_required
def delete_folder_from_trash(folder_id):
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id, is_deleted=True).first()
    if not folder:
        return jsonify({'error': 'Folder not found in trash'}), 404

    reclaimed = 0
    files = SharedFile.query.filter_by(user_id=user_id, folder_id=folder.id, is_deleted=True).all()
    for file_info in files:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], user_id, file_info.stored_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        reclaimed += file_info.size
        db.session.delete(file_info)

    user.storage_used = max(0, (user.storage_used or 0) - reclaimed)
    log_action('trash_delete', folder.name)
    db.session.delete(folder)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Folder permanently deleted'})


@files_bp.route('/api/trash/empty', methods=['POST'])
@login_required
def empty_trash():
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required'}), 401
    trash_files = SharedFile.query.filter_by(user_id=user_id, is_deleted=True).all()
    trash_folders = Folder.query.filter_by(user_id=user_id, is_deleted=True).all()
    if not trash_files and not trash_folders:
        return jsonify({'success': True, 'message': 'Trash already empty'})

    reclaimed = 0
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], user_id)
    processed = set()

    for folder in trash_folders:
        files = SharedFile.query.filter_by(user_id=user_id, folder_id=folder.id, is_deleted=True).all()
        for file_info in files:
            file_path = os.path.join(upload_dir, file_info.stored_name)
            if os.path.exists(file_path):
                os.remove(file_path)
            reclaimed += file_info.size
            processed.add(file_info.id)
            db.session.delete(file_info)
        db.session.delete(folder)

    for file_info in trash_files:
        if file_info.id in processed:
            continue
        file_path = os.path.join(upload_dir, file_info.stored_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        reclaimed += file_info.size
        db.session.delete(file_info)

    user.storage_used = max(0, (user.storage_used or 0) - reclaimed)
    log_action('trash_delete', file_name='__empty_trash__')
    db.session.commit()
    return jsonify({'success': True, 'message': 'Trash emptied'})
