import os
import mimetypes
import traceback
from flask import current_app
import io
import zipfile
from datetime import datetime
from flask import jsonify
from flask import (
    Flask, request, send_from_directory, send_file,
    render_template, redirect, url_for, flash, abort, session
)
from werkzeug.utils import secure_filename

BASE_DIR = "/mnt/nasdrive" # Change to your desired base directory
ITEMS_PER_PAGE = 20

app = Flask(__name__)
app.secret_key = 'CHANGE_THIS_SECRET_KEY'

# Credentials (change these!)
AUTH_USERNAME = 'Username' 
AUTH_PASSWORD = 'password'

def secure_path(subpath):
    full_path = os.path.abspath(os.path.join(BASE_DIR, subpath))
    if not full_path.startswith(BASE_DIR):
        return BASE_DIR
    return full_path

@app.template_filter('datetimeformat')
def datetimeformat(value):
    if not value:
        return ''
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')

def human_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

app.jinja_env.filters['human_size'] = human_size

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if username == AUTH_USERNAME and password == AUTH_PASSWORD:
            session['logged_in'] = True
            next_page = request.args.get('next') or url_for('index')
            return redirect(next_page)
        else:
            error = "Invalid username or password."
    return render_template('login.html', error=error)

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/', defaults={'req_path': ''})
@app.route('/<path:req_path>')
@login_required
def index(req_path):
    page = int(request.args.get('page', 1))
    search_query = request.args.get('search', '').lower()

    abs_path = secure_path(req_path)
    if not os.path.exists(abs_path):
        return f"Path not found: {abs_path}", 404

    if os.path.isfile(abs_path):
        return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=False)

    hidden = {'lost+found', 'kali'}

    all_entries = []
    for entry in os.listdir(abs_path):
        if entry in hidden:
            continue
        if search_query and search_query not in entry.lower():
            continue
        full_entry = os.path.join(abs_path, entry)
        is_dir = os.path.isdir(full_entry)
        size = os.path.getsize(full_entry) if not is_dir else 0
        mtime = os.path.getmtime(full_entry)
        ext = os.path.splitext(entry)[1].lower() if not is_dir else ''
        mime_type = mimetypes.guess_type(entry)[0] if not is_dir else ''
        all_entries.append({
            'name': entry,
            'is_dir': is_dir,
            'size': size,
            'mtime': mtime,
            'ext': ext,
            'mime_type': mime_type,
        })

    all_entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    total_items = len(all_entries)
    pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start = (page - 1) * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    entries = all_entries[start:end]

    parent = os.path.relpath(os.path.join(abs_path, ".."), BASE_DIR)
    if parent == '.':
        parent = ''

    return render_template('index.html',
                           files=entries,
                           current_path=req_path,
                           parent_path=parent,
                           page=page,
                           pages=pages,
                           search=search_query)

@app.route('/upload/', methods=['POST'])
@app.route('/upload/<path:req_path>', methods=['POST'])
def upload(req_path=''):
    try:
        target_dir = secure_path(req_path)
        files = request.files.getlist('file')
        if not files:
            return "No files uploaded", 400

        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                save_path = os.path.join(target_dir, filename)
                file.save(save_path)

        flash("Upload successful")
        return redirect(url_for('index', req_path=req_path))
    except Exception as e:
        current_app.logger.error('Upload error:\n' + traceback.format_exc())
        return f"Upload failed: {str(e)}", 500


@app.route('/mkdir/', methods=['POST'])
@app.route('/mkdir/<path:req_path>', methods=['POST'])
def mkdir(req_path=''):

    target_dir = secure_path(req_path)
    folder_name = request.form.get('foldername', '').strip()
    if folder_name:
        safe_folder = secure_filename(folder_name)
        new_path = os.path.join(target_dir, safe_folder)
        try:
            os.makedirs(new_path, exist_ok=True)
            flash(f"Folder '{safe_folder}' created")
        except Exception as e:
            flash(f"Error creating folder: {e}")
    else:
        flash("Folder name cannot be empty")
    return redirect(url_for('index', req_path=req_path))

@app.route('/move', methods=['POST'])
def move():
    data = request.get_json()
    src = data.get('src')
    dst = data.get('dst')
    if not src or not dst:
        return jsonify({'error': 'Missing src or dst'}), 400

    src_path = secure_path(src)
    dst_path = secure_path(dst)
    if not os.path.exists(src_path) or not os.path.isdir(dst_path):
        return jsonify({'error': 'Invalid source or destination'}), 400

    filename = os.path.basename(src_path)
    new_path = os.path.join(dst_path, filename)
    try:
        os.rename(src_path, new_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download-folder/<path:req_path>')
@login_required
def download_folder(req_path):
    folder_path = secure_path(req_path)
    if not os.path.isdir(folder_path):
        return "Not a folder", 400

    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, mode='w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                abs_file = os.path.join(root, file)
                rel_path = os.path.relpath(abs_file, folder_path)
                zipf.write(abs_file, rel_path)
    zip_io.seek(0)
    folder_name = os.path.basename(folder_path.rstrip("/"))
    return send_file(zip_io, mimetype='application/zip', as_attachment=True, download_name=f"{folder_name}.zip")

@app.route('/delete/<path:req_path>', methods=['POST'])
@login_required
def delete(req_path):
    target_path = secure_path(req_path)
    try:
        if os.path.isdir(target_path):
            import shutil
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
        flash(f"Deleted '{req_path}'")
    except Exception as e:
        flash(f"Error deleting: {e}")
    parent_path = os.path.dirname(req_path)
    return redirect(url_for('index', req_path=parent_path))

@app.route('/rename/<path:req_path>', methods=['POST'])
@login_required
def rename(req_path):
    target_path = secure_path(req_path)
    new_name = request.form.get('newname', '').strip()
    if not new_name:
        flash("New name cannot be empty")
        return redirect(url_for('index', req_path=req_path))
    safe_new_name = secure_filename(new_name)
    new_path = os.path.join(os.path.dirname(target_path), safe_new_name)
    try:
        os.rename(target_path, new_path)
        flash(f"Renamed to '{safe_new_name}'")
    except Exception as e:
        flash(f"Error renaming: {e}")
    parent_path = os.path.dirname(req_path)
    return redirect(url_for('index', req_path=parent_path))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)

