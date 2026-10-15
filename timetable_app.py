import os
import sys

# Ensure isolated local libraries are loaded (for local dev only)
_libs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs')
if os.path.exists(_libs_dir) and _libs_dir not in sys.path:
    sys.path.insert(0, _libs_dir)

import datetime
import random
import json
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from functools import wraps


app = Flask(__name__, template_folder='templates_2')
app.secret_key = os.environ.get('SECRET_KEY', 'default-timetable-secret-key-change-in-prod')

# ------------------------------------------------------------------
# Persistent DB path:
#   - On Render with a Disk mounted at /data  → use /data/faculty_data.json
#   - Locally or without disk                 → use file next to app
# ------------------------------------------------------------------
_DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
FACULTY_DB_PATH = os.path.join(_DATA_DIR, 'faculty_data.json')

# Remove any legacy SQLite DB files
for _old_db in ['timetable.db', 'faculty.db', 'database.db', 'timetable.sqlite']:
    _old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _old_db)
    if os.path.exists(_old_path):
        try:
            os.remove(_old_path)
        except Exception:
            pass


# ------------------------------------------------------------------
# Faculty persistence helpers
# ------------------------------------------------------------------
def load_faculty():
    """Load faculty list from persistent JSON storage."""
    if not os.path.exists(FACULTY_DB_PATH):
        return []
    try:
        with open(FACULTY_DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_faculty(faculty_list):
    """Save faculty list to persistent JSON storage."""
    try:
        os.makedirs(os.path.dirname(FACULTY_DB_PATH), exist_ok=True)
        with open(FACULTY_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(faculty_list, f, indent=4)
        return True
    except Exception:
        return False


def clean_faculty_entry(item):
    """Normalise one faculty dict coming from form or API."""
    name = str(item.get('name', '')).strip()
    abbr = str(item.get('abbr', '')).strip()
    subject = str(item.get('subject', '')).strip()
    th = item.get('theory_hours', 0)
    ph = item.get('practical_hours', 0)
    batches = item.get('practical_batches', [])
    if isinstance(batches, str):
        batches = [b.strip() for b in batches.split(',') if b.strip()]
    return {
        'name': name,
        'abbr': abbr if abbr else name[:3].upper(),
        'subject': subject,
        'theory_hours': int(th) if str(th).isdigit() else 0,
        'practical_hours': int(ph) if str(ph).isdigit() else 0,
        'practical_batches': batches,
    }


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
VALID_CREDENTIALS = {
    'admin': 'admin',
    'user': 'password'
}


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username in VALID_CREDENTIALS and VALID_CREDENTIALS[username] == password:
            session['username'] = username
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid username or password')
    if 'username' in session:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ------------------------------------------------------------------
# Main pages
# ------------------------------------------------------------------
@app.route('/')
@login_required
def index():
    saved_faculty = load_faculty()
    return render_template('timetable_form.html', saved_faculty=saved_faculty)


@app.route('/faculty')
@login_required
def faculty_dashboard():
    faculty_list = load_faculty()
    return render_template('faculty.html', faculty_list=faculty_list)


# ------------------------------------------------------------------
# Faculty CRUD
# ------------------------------------------------------------------
@app.route('/faculty/add', methods=['POST'])
@login_required
def add_faculty():
    entry = clean_faculty_entry({
        'name':             request.form.get('name', ''),
        'abbr':             request.form.get('abbr', ''),
        'subject':          request.form.get('subject', ''),
        'theory_hours':     request.form.get('theory_hours', '0'),
        'practical_hours':  request.form.get('practical_hours', '0'),
        'practical_batches': request.form.get('practical_batches', ''),
    })
    if entry['name'] and entry['subject']:
        faculty_list = load_faculty()
        faculty_list.append(entry)
        save_faculty(faculty_list)
        return render_template('faculty.html', faculty_list=faculty_list,
                               message=f"Added '{entry['name']}' successfully!")
    return redirect(url_for('faculty_dashboard'))


@app.route('/faculty/delete/<int:index>', methods=['POST'])
@login_required
def delete_faculty(index):
    faculty_list = load_faculty()
    if 0 <= index < len(faculty_list):
        removed = faculty_list.pop(index)
        save_faculty(faculty_list)
        return render_template('faculty.html', faculty_list=faculty_list,
                               message=f"Removed '{removed.get('name')}' successfully!")
    return redirect(url_for('faculty_dashboard'))


@app.route('/faculty/clear', methods=['POST'])
@login_required
def clear_faculty():
    save_faculty([])
    return render_template('faculty.html', faculty_list=[],
                           message="All faculty records have been cleared.")


@app.route('/api/faculty/save-all', methods=['POST'])
@login_required
def api_save_all_faculty():
    data = request.get_json(silent=True)
    if data and isinstance(data.get('faculty'), list):
        clean_list = [clean_faculty_entry(item) for item in data['faculty']
                      if item.get('name') or item.get('subject')]
        save_faculty(clean_list)
        return jsonify({"status": "success", "count": len(clean_list)})
    return jsonify({"status": "error", "message": "Invalid payload"}), 400


# ------------------------------------------------------------------
# Timetable generation
# ------------------------------------------------------------------
BATCHES = ['A1', 'A2', 'A3', 'A4']


def build_time_slots(start, end, lec_dur, breaks):
    """Return list of time-slot dicts with is_break flag."""
    current_time = start
    time_slots = []
    while current_time < end:
        next_break = None
        for b in breaks:
            if b['start'] <= current_time < b['end'] or current_time <= b['start'] < current_time + lec_dur:
                next_break = b
                break
        if next_break:
            if current_time >= next_break['start']:
                time_slots.append({
                    "time": f"{current_time.strftime('%H:%M')} - {next_break['end'].strftime('%H:%M')}",
                    "is_break": True,
                    "label": next_break['label']
                })
                current_time = next_break['end']
            else:
                slot_end = next_break['start']
                time_slots.append({
                    "time": f"{current_time.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                    "is_break": False
                })
                current_time = slot_end
        else:
            slot_end = min(current_time + lec_dur, end)
            time_slots.append({
                "time": f"{current_time.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                "is_break": False
            })
            current_time = slot_end
    return time_slots


@app.route('/generate', methods=['POST'])
@login_required
def generate():
    # ── Config ────────────────────────────────────────────────────
    config = {
        'start_time':         request.form.get('start_time', '09:00'),
        'end_time':           request.form.get('end_time', '16:00'),
        'lecture_duration':   request.form.get('lecture_duration', '60'),
        'practical_duration': request.form.get('practical_duration', '90'),
        'num_classrooms':     int(request.form.get('num_classrooms', '5')),
        'num_classes':        int(request.form.get('num_classes', '2')),
        'num_labs':           int(request.form.get('num_labs', '2')),
        'free_lectures':      int(request.form.get('free_lectures', '0')),
        'working_days':       request.form.getlist('working_days'),
        'num_batches':        int(request.form.get('num_batches', '4')),
    }
    if not config['working_days']:
        config['working_days'] = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

    start   = datetime.datetime.strptime(config['start_time'], '%H:%M')
    end     = datetime.datetime.strptime(config['end_time'], '%H:%M')
    lec_dur = datetime.timedelta(minutes=int(config['lecture_duration']))
    prac_dur_mins = int(config['practical_duration'])

    # ── Faculty from form (or fallback to saved DB) ────────────────
    faculty_names     = request.form.getlist('faculty_name[]')
    faculty_abbrs     = request.form.getlist('faculty_abbr[]')
    faculty_subjects  = request.form.getlist('faculty_subject[]')
    faculty_hours     = request.form.getlist('faculty_hours[]')
    faculty_prac_hrs  = request.form.getlist('faculty_practical_hours[]')
    faculty_batches   = request.form.getlist('faculty_batches[]')   # comma-separated per row

    faculty_list = []
    for n, ab, s, h, ph, fb in zip(faculty_names, faculty_abbrs, faculty_subjects,
                                    faculty_hours, faculty_prac_hrs, faculty_batches):
        if n or s:
            batches = [b.strip() for b in fb.split(',') if b.strip()] if fb else []
            faculty_list.append({
                'name':             n.strip(),
                'abbr':             ab.strip() if ab.strip() else n.strip()[:3].upper(),
                'subject':          s.strip(),
                'theory_hours':     int(h)  if h  and h.isdigit()  else 0,
                'practical_hours':  int(ph) if ph and ph.isdigit() else 0,
                'practical_batches': batches,
            })

    if faculty_list:
        save_faculty(faculty_list)
    else:
        faculty_list = load_faculty()
    if not faculty_list:
        faculty_list = [{"name": "Default Faculty", "abbr": "DEF",
                         "subject": "General Study", "theory_hours": 4,
                         "practical_hours": 0, "practical_batches": []}]

    # ── Breaks ────────────────────────────────────────────────────
    raw_starts = request.form.getlist('break_start[]')
    raw_ends   = request.form.getlist('break_end[]')
    raw_labels = request.form.getlist('break_label[]')
    breaks = []
    for bs, be, bl in zip(raw_starts, raw_ends, raw_labels):
        if bs and be:
            breaks.append({
                "start": datetime.datetime.strptime(bs, '%H:%M'),
                "end":   datetime.datetime.strptime(be, '%H:%M'),
                "label": bl if bl else "Break"
            })

    # ── Time slots ────────────────────────────────────────────────
    time_slots = build_time_slots(start, end, lec_dur, breaks)

    # ── Active batches ────────────────────────────────────────────
    active_batches = BATCHES[:config['num_batches']]

    # ── Resources ────────────────────────────────────────────────
    class_ids = [f"Class/Section {i+1}" for i in range(config['num_classes'])]
    rooms     = [f"Room {101 + i}" for i in range(config['num_classrooms'])] or ["Room A"]
    labs      = [f"Lab {i+1}" for i in range(config['num_labs'])] or []

    # ── Separate theory vs practical faculty ──────────────────────
    theory_faculty   = [f for f in faculty_list if f.get('theory_hours', 0) > 0]
    practical_faculty = [f for f in faculty_list if f.get('practical_hours', 0) > 0]

    if not theory_faculty:
        theory_faculty = faculty_list   # fallback

    # ── Per-class free slots ──────────────────────────────────────
    valid_coords = [(d, idx) for d in config['working_days']
                    for idx, s in enumerate(time_slots) if not s['is_break']]
    free_slots_map = {
        c_id: set(random.sample(valid_coords, min(config['free_lectures'], len(valid_coords))))
        for c_id in class_ids
    }

    # ── Theory schedule per class ─────────────────────────────────
    class_schedules = {c: {d: [] for d in config['working_days']} for c in class_ids}

    for slot_idx, slot in enumerate(time_slots):
        for d in config['working_days']:
            if slot['is_break']:
                for c_id in class_ids:
                    class_schedules[c_id][d].append(None)
            else:
                classes_needing = []
                for c_id in class_ids:
                    if (d, slot_idx) in free_slots_map[c_id]:
                        class_schedules[c_id][d].append({
                            "subject": "Free Time", "faculty": "-",
                            "abbr": "-", "room": "-", "type": "free"
                        })
                    else:
                        classes_needing.append(c_id)

                random.shuffle(theory_faculty)
                random.shuffle(rooms)
                for i, c_id in enumerate(classes_needing):
                    fac  = theory_faculty[i % len(theory_faculty)]
                    room = rooms[i % len(rooms)]
                    class_schedules[c_id][d].append({
                        "subject": fac['subject'] or "-",
                        "faculty": fac['name']    or "-",
                        "abbr":    fac.get('abbr', fac['name'][:3].upper()),
                        "room":    room,
                        "type":    "theory"
                    })

    # ── Practical schedule per batch ──────────────────────────────
    # Build a flat list of slots long enough to cover the week
    # Each practical slot spans prac_dur_mins (may span multiple theory slots)
    slot_mins = int(config['lecture_duration'])
    slots_per_practical = max(1, prac_dur_mins // slot_mins)

    batch_schedules = {b: {d: [] for d in config['working_days']} for b in active_batches}

    # Build non-break slot index lists per day
    non_break_by_day = {
        d: [idx for idx, s in enumerate(time_slots) if not s['is_break']]
        for d in config['working_days']
    }

    for batch in active_batches:
        # Faculty responsible for this batch
        batch_fac_pool = [f for f in practical_faculty
                          if batch in f.get('practical_batches', [])]
        if not batch_fac_pool:
            batch_fac_pool = practical_faculty if practical_faculty else theory_faculty

        lab_pool = labs if labs else rooms   # use rooms as fallback for labs

        fac_idx = 0
        for d in config['working_days']:
            nb_slots = non_break_by_day[d]
            # Assign practicals in chunks
            i = 0
            while i < len(nb_slots):
                chunk_start = nb_slots[i]
                chunk_end_offset = min(i + slots_per_practical, len(nb_slots))
                chunk_end = nb_slots[chunk_end_offset - 1]

                start_time_str = time_slots[chunk_start]['time'].split(' - ')[0]
                end_time_str   = time_slots[chunk_end]['time'].split(' - ')[1]

                fac  = batch_fac_pool[fac_idx % len(batch_fac_pool)]
                lab  = lab_pool[(fac_idx // len(batch_fac_pool)) % len(lab_pool)]
                fac_idx += 1

                batch_schedules[batch][d].append({
                    "time":    f"{start_time_str} - {end_time_str}",
                    "subject": fac['subject'],
                    "faculty": fac['name'],
                    "abbr":    fac.get('abbr', fac['name'][:3].upper()),
                    "lab":     lab,
                    "slots":   slots_per_practical,
                })
                i += slots_per_practical

    return render_template(
        'timetable.html',
        config=config,
        time_slots=time_slots,
        schedules=class_schedules,
        batch_schedules=batch_schedules,
        active_batches=active_batches,
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
