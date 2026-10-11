# -*- coding: utf-8 -*-
# app.py - Журнал 3D (исправленная версия: undo/redo + совместимость сортировки)
from datetime import date, datetime
import os
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
DB_NAME = 'journal.db'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

STATUS_FIELDS = ('cloud', 'analysis', 'e57')
COLORS = {'done', 'partial', 'issue', 'warn', 'na', None}
FIELDS = {'cloud', 'analysis', 'e57'}


# ---------------------------------------------------------------- БД
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('''
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_num TEXT NOT NULL,
                employee TEXT,
                scan_date TEXT,
                object_name TEXT,
                notes TEXT,
                file_path TEXT,
                is_deleted INTEGER DEFAULT 0,
                deleted_at TEXT
            )
        ''')

        c.execute("PRAGMA table_info(journal)")
        existing_cols = {row['name'] for row in c.fetchall()}

        columns_to_ensure = [
            ('cloud_code', 'TEXT'), ('cloud_note', 'TEXT'), ('cloud_by', 'TEXT'), ('cloud_at', 'TEXT'),
            ('analysis_code', 'TEXT'), ('analysis_note', 'TEXT'), ('analysis_by', 'TEXT'), ('analysis_at', 'TEXT'),
            ('e57_code', 'TEXT'), ('e57_note', 'TEXT'), ('e57_by', 'TEXT'), ('e57_at', 'TEXT')
        ]

        for col_name, col_def in columns_to_ensure:
            if col_name not in existing_cols:
                try:
                    c.execute(f"ALTER TABLE journal ADD COLUMN {col_name} {col_def}")
                    print(f">>> Колонка '{col_name}' добавлена.")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e):
                        raise e

        conn.commit()
        print(">>> Инициализация базы данных завершена успешно.")
    except sqlite3.Error as e:
        print(f">>> Критическая ошибка при инициализации БД: {e}")
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------- ХЕЛПЕРЫ
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1).lower() in ALLOWED_EXTENSIONS


def status_payload(row_dict, field):
    # Гарантированно возвращает словарь статуса, даже если в БД NULL
    return {
        'code': row_dict.get(field + '_code'),
        'note': row_dict.get(field + '_note'),
        'by':   row_dict.get(field + '_by'),
        'at':   row_dict.get(field + '_at'),
    }


def get_trash_count():
    conn = get_db_connection()
    try:
        return conn.execute('SELECT COUNT(*) AS c FROM journal WHERE is_deleted = 1').fetchone()['c']
    finally:
        conn.close()


# ---------------------------------------------------------------- МАРШРУТЫ
@app.route('/')
def index():
    sort = request.args.get('sort', 'desc')
    if sort not in ('asc', 'desc'):
        sort = 'desc'
    search_query = request.args.get('q', '').strip()
    is_admin = request.args.get('admin') == 'true'

    conn = get_db_connection()
    try:
        # ИСПРАВЛЕНО: "NULLS LAST" есть не во всех сборках SQLite (падает на старых Python).
        # Тот же смысл через флаг "дата пустая" - работает на любом SQLite.
        order_sql = 'ORDER BY (scan_date IS NULL) ASC, scan_date ' + sort + ', id DESC'

        if search_query:
            rows = conn.execute(f'''
                SELECT * FROM journal
                WHERE is_deleted = 0 AND (order_num LIKE ? OR employee LIKE ? OR object_name LIKE ?)
                {order_sql}
            ''', (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%')).fetchall()
        else:
            rows = conn.execute(f'''
                SELECT * FROM journal
                WHERE is_deleted = 0
                {order_sql}
            ''').fetchall()

        clean_data = []
        for row in rows:
            r = dict(row)
            for f in STATUS_FIELDS:
                r[f + '_status'] = status_payload(r, f)
            clean_data.append(r)

        return render_template('index.html',
                               journal_data=clean_data,
                               search_query=search_query,
                               sort=sort,
                               is_admin=is_admin,
                               trash_count=get_trash_count())
    finally:
        conn.close()


@app.route('/api/trash-count')
def api_trash_count():
    return jsonify({'count': get_trash_count()})


@app.route('/trash')
def trash():
    is_admin = request.args.get('admin') == 'true'
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM journal WHERE is_deleted = 1 ORDER BY deleted_at DESC'
        ).fetchall()
        return render_template('trash.html', journal_data=rows, is_admin=is_admin)
    finally:
        conn.close()


@app.route('/add', methods=('GET', 'POST'))
def add():
    is_admin = request.args.get('admin') == 'true'
    if not is_admin:
        return "Доступ запрещен. Только для администраторов.", 403

    if request.method == 'POST':
        order_num = request.form['order_num'].replace('\xa0', ' ').strip()
        employee = request.form.get('employee', '').strip()
        scan_date = request.form.get('scan_date', '').strip()
        object_name = request.form.get('object_name', '').strip()
        notes = request.form.get('notes', '')
        file_path = None

        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{order_num or 'no_order'}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                file_path = unique_filename

        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO journal (order_num, employee, scan_date, object_name, notes, file_path, is_deleted) '
                'VALUES (?, ?, ?, ?, ?, ?, 0)',
                (order_num, employee, scan_date, object_name, notes, file_path))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error adding record: {e}")
        finally:
            conn.close()

        return redirect(url_for('index') + ('?admin=true' if is_admin else ''))

    today = date.today().isoformat()
    return render_template('add.html', is_admin=True, default_date=today)


@app.route('/edit/<int:id>', methods=('GET', 'POST'))
def edit(id):
    is_admin = request.args.get('admin') == 'true'
    if not is_admin:
        return "Доступ запрещен.", 403

    conn = get_db_connection()
    try:
        if request.method == 'POST':
            order_num = request.form['order_num'].replace('\xa0', ' ').strip()
            employee = request.form.get('employee', '').strip()
            scan_date = request.form.get('scan_date', '').strip()
            object_name = request.form.get('object_name', '').strip()
            notes = request.form.get('notes', '')
            file_path = None

            if 'file' in request.files:
                file = request.files['file']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"edit_{id}_{filename}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    file_path = unique_filename

            if not file_path:
                existing = conn.execute('SELECT file_path FROM journal WHERE id = ?', (id,)).fetchone()
                file_path = existing['file_path'] if existing else None

            conn.execute('UPDATE journal SET order_num=?, employee=?, scan_date=?, object_name=?, notes=?, file_path=? WHERE id=?',
                         (order_num, employee, scan_date, object_name, notes, file_path, id))
            conn.commit()
            return redirect(url_for('index') + '?admin=true')

        row = conn.execute('SELECT * FROM journal WHERE id = ?', (id,)).fetchone()
        if row is None:
            return "Запись не найдена", 404
        return render_template('edit.html', data=row, is_admin=True)
    except Exception as e:
        conn.rollback()
        print(f"Error editing record: {e}")
        return "Произошла ошибка при редактировании", 500
    finally:
        conn.close()


@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    if request.args.get('admin') != 'true':
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    conn = get_db_connection()
    try:
        cur = conn.execute('UPDATE journal SET is_deleted = 1, deleted_at = ? WHERE id = ?',
                           (datetime.now().isoformat(timespec='seconds'), id))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'status': 'error', 'message': 'Запись не найдена'}), 404
        return jsonify({'status': 'ok', 'action': 'delete', 'id': id, 'count': get_trash_count()})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()


@app.route('/restore/<int:id>', methods=['POST'])
def restore(id):
    if request.args.get('admin') != 'true':
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    conn = get_db_connection()
    try:
        cur = conn.execute('UPDATE journal SET is_deleted = 0, deleted_at = NULL WHERE id = ?', (id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'status': 'error', 'message': 'Запись не найдена'}), 404
        return jsonify({'status': 'ok', 'action': 'restore', 'id': id, 'count': get_trash_count()})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()


@app.route('/purge/<int:id>', methods=['POST'])
def purge(id):
    if request.args.get('admin') != 'true':
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT file_path FROM journal WHERE id = ?', (id,)).fetchone()
        if row and row['file_path']:
            p = os.path.join(app.config['UPLOAD_FOLDER'], row['file_path'])
            if os.path.exists(p):
                os.remove(p)

        conn.execute('DELETE FROM journal WHERE id = ?', (id,))
        conn.commit()
        return jsonify({'status': 'ok', 'action': 'purge', 'id': id, 'count': get_trash_count()})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()


@app.route('/status/<int:id>/<field>', methods=['POST'])
def set_status(id, field):
    if request.args.get('admin') != 'true':
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    if field not in FIELDS:
        return jsonify({'status': 'error', 'message': 'Недопустимое поле'}), 400

    data = request.get_json(silent=True) or {}
    code = data.get('code')
    if code == '':          # фронт может прислать пустую строку - считаем это сбросом
        code = None
    if code not in COLORS:
        return jsonify({'status': 'error', 'message': 'Недопустимый код статуса'}), 400

    conn = None
    try:
        conn = get_db_connection()

        old = conn.execute('SELECT * FROM journal WHERE id=?', (id,)).fetchone()
        if old is None:
            return jsonify({'status': 'error', 'message': 'Запись не найдена'}), 404
        prev = status_payload(dict(old), field)   # сервер отдаёт прежнее состояние

        if code is None:
            conn.execute(f'''
                UPDATE journal
                SET {field}_code=NULL, {field}_note=NULL,
                    {field}_by=NULL, {field}_at=NULL
                WHERE id=?
            ''', (id,))
            nxt = {'code': None, 'note': '', 'by': '', 'at': None}
        else:
            note = (data.get('note') or '').strip() or None
            by = (data.get('by') or '').strip() or None
            now = datetime.now().isoformat(timespec='seconds')
            conn.execute(f'''
                UPDATE journal
                SET {field}_code=?, {field}_note=?, {field}_by=?, {field}_at=?
                WHERE id=?
            ''', (code, note, by, now, id))
            nxt = {'code': code, 'note': note or '', 'by': by or '', 'at': now}

        conn.commit()
        return jsonify({'status': 'ok', 'id': id, 'field': field, 'code': code,
                        'prev': prev, 'next': nxt})

    except sqlite3.OperationalError as e:
        print(f"DB busy (timeout): {e}")
        return jsonify({'status': 'error', 'message': 'База данных временно занята. Попробуйте позже.'}), 503
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"CRITICAL set_status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.route('/download_excel')
def download_excel():
    if request.args.get('admin') != 'true':
        return "Доступ запрещен.", 403

    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM journal WHERE is_deleted = 0 ORDER BY id DESC", conn)
        for col in ('id', 'file_path', 'is_deleted', 'deleted_at'):
            if col in df.columns:
                df = df.drop(columns=[col])
        df.to_excel('journal_export.xlsx', index=False)
        return send_from_directory('.', 'journal_export.xlsx', as_attachment=True)
    except Exception as e:
        print(f"Error exporting Excel: {e}")
        return "Ошибка при создании файла Excel", 500
    finally:
        conn.close()


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='127.0.0.1', port=5000)
