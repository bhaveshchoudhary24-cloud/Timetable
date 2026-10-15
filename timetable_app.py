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
        'abbr': abbr if abbr else (name[:3].upper() if name else 'FAC'),
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
# Timetable generation helpers
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
                    "time": f"{current_time.strftime('%I:%M%p').lower()} to {next_break['end'].strftime('%I:%M%p').lower()}",
                    "raw_time": f"{current_time.strftime('%H:%M')} - {next_break['end'].strftime('%H:%M')}",
                    "is_break": True,
                    "label": next_break['label']
                })
                current_time = next_break['end']
            else:
                slot_end = next_break['start']
                time_slots.append({
                    "time": f"{current_time.strftime('%I:%M%p').lower()} to {slot_end.strftime('%I:%M%p').lower()}",
                    "raw_time": f"{current_time.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                    "is_break": False
                })
                current_time = slot_end
        else:
            slot_end = min(current_time + lec_dur, end)
            time_slots.append({
                "time": f"{current_time.strftime('%I:%M%p').lower()} to {slot_end.strftime('%I:%M%p').lower()}",
                "raw_time": f"{current_time.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                "is_break": False
            })
            current_time = slot_end
    return time_slots


@app.route('/generate', methods=['POST'])
@login_required
def generate():
    # ── Configuration & Metadata ──────────────────────────────────
    config = {
        'college_name':       request.form.get('college_name', "Marathwada Mitra Mandal's Institute of Technology, Lohgaon Pune - 47"),
        'dept_name':          request.form.get('dept_name', "Department of Computer Engineering"),
        'academic_year':      request.form.get('academic_year', "A.Y.2026-27"),
        'semester':           request.form.get('semester', "Semester : 5"),
        'class_name':         request.form.get('class_name', "Class: TE"),
        'division':           request.form.get('division', "Division: A"),
        'wef_date':           request.form.get('wef_date', "w.e.f. - 01/07/2026"),
        'start_time':         request.form.get('start_time', '08:30'),
        'end_time':           request.form.get('end_time', '15:30'),
        'lecture_duration':   request.form.get('lecture_duration', '60'),
        'practical_duration': request.form.get('practical_duration', '120'),
        'num_classrooms':     int(request.form.get('num_classrooms', '5')),
        'num_classes':        int(request.form.get('num_classes', '1')),
        'num_labs':           int(request.form.get('num_labs', '4')),
        'free_lectures':      int(request.form.get('free_lectures', '0')),
        'working_days':       request.form.getlist('working_days'),
        'num_batches':        int(request.form.get('num_batches', '4')),
    }
    if not config['working_days']:
        config['working_days'] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    else:
        # Normalize day names to full names for display
        day_map = {
            'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday',
            'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday',
            'Monday': 'Monday', 'Tuesday': 'Tuesday', 'Wednesday': 'Wednesday',
            'Thursday': 'Thursday', 'Friday': 'Friday', 'Saturday': 'Saturday'
        }
        config['working_days'] = [day_map.get(d, d) for d in config['working_days']]

    start   = datetime.datetime.strptime(config['start_time'], '%H:%M')
    end     = datetime.datetime.strptime(config['end_time'], '%H:%M')
    lec_dur = datetime.timedelta(minutes=int(config['lecture_duration']))

    # ── Faculty from form (or fallback to saved DB) ────────────────
    faculty_names     = request.form.getlist('faculty_name[]')
    faculty_abbrs     = request.form.getlist('faculty_abbr[]')
    faculty_subjects  = request.form.getlist('faculty_subject[]')
    faculty_hours     = request.form.getlist('faculty_hours[]')
    faculty_prac_hrs  = request.form.getlist('faculty_practical_hours[]')
    faculty_batches   = request.form.getlist('faculty_batches[]')

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
                         "subject": "General Study", "theory_hours": 3,
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

    # Default breaks if none specified
    if not breaks:
        breaks = [
            {"start": datetime.datetime.strptime("10:30", "%H:%M"), "end": datetime.datetime.strptime("10:45", "%H:%M"), "label": "Short Recess"},
            {"start": datetime.datetime.strptime("12:45", "%H:%M"), "end": datetime.datetime.strptime("13:30", "%H:%M"), "label": "Lunch Break"}
        ]

    # ── Build Time Slots ──────────────────────────────────────────
    time_slots = build_time_slots(start, end, lec_dur, breaks)

    # ── Active batches & Resources ────────────────────────────────
    active_batches = BATCHES[:config['num_batches']]
    class_ids = [f"Class {i+1}" if config['num_classes'] > 1 else config['class_name'] for i in range(config['num_classes'])]
    rooms     = [f"E{101 + i}" for i in range(config['num_classrooms'])] or ["E102"]
    labs      = [f"C{101 + i}" for i in range(config['num_labs'])] or [f"Lab {i+1}" for i in range(4)]

    # Separate Theory & Practical faculty
    theory_faculty   = [f for f in faculty_list if f.get('theory_hours', 0) > 0]
    practical_faculty = [f for f in faculty_list if f.get('practical_hours', 0) > 0]
    if not theory_faculty:
        theory_faculty = faculty_list

    # Non-break slots indices
    non_break_indices = [idx for idx, s in enumerate(time_slots) if not s['is_break']]

    # ── Plan Practical Slot Blocks (2-slot practical sessions) ────
    # For a realistic schedule like the reference:
    # We select 1 practical session (2 consecutive lecture slots) on days with practicals
    # Morning practical block or afternoon practical block
    practical_slots_by_day = {}
    if practical_faculty and len(non_break_indices) >= 2:
        for day_idx, d in enumerate(config['working_days']):
            # Pick a 2-consecutive non-break slot window for practicals
            # Alternates between morning (slots 0,1) and late morning (slots 2,3)
            # Find candidate pairs of adjacent non-break slots
            pairs = []
            for i in range(len(non_break_indices) - 1):
                idx1 = non_break_indices[i]
                idx2 = non_break_indices[i+1]
                if idx2 == idx1 + 1:
                    pairs.append((idx1, idx2))
            
            if pairs:
                # Pick pair based on day
                chosen_pair = pairs[day_idx % len(pairs)]
                practical_slots_by_day[d] = set(chosen_pair)
            else:
                practical_slots_by_day[d] = set()
    else:
        for d in config['working_days']:
            practical_slots_by_day[d] = set()

    # ── Generate Unified Master Schedule per Class ────────────────
    # class_schedules[class_id][day][slot_idx] = cell_dict
    class_schedules = {c: {d: [None] * len(time_slots) for d in config['working_days']} for c in class_ids}

    # Tracking rotational indices for balance
    theory_cycle_idx = 0
    prac_cycle_idx = 0

    for c_idx, c_id in enumerate(class_ids):
        assigned_room = rooms[c_idx % len(rooms)]

        for d in config['working_days']:
            prac_slots_today = practical_slots_by_day.get(d, set())

            # Pre-generate today's batch practical assignments if today has a practical block
            today_batch_assignments = []
            if prac_slots_today and practical_faculty:
                used_fac_abbrs = set()
                for b_idx, batch in enumerate(active_batches):
                    # Filter faculty for this batch
                    eligible = [f for f in practical_faculty if batch in f.get('practical_batches', []) and f.get('abbr') not in used_fac_abbrs]
                    if not eligible:
                        eligible = [f for f in practical_faculty if f.get('abbr') not in used_fac_abbrs]
                    if not eligible:
                        eligible = practical_faculty

                    fac = eligible[(prac_cycle_idx + b_idx) % len(eligible)]
                    used_fac_abbrs.add(fac.get('abbr'))
                    lab = labs[b_idx % len(labs)]
                    today_batch_assignments.append({
                        'batch': batch,
                        'subject': fac.get('subject', 'PRAC'),
                        'abbr': fac.get('abbr', fac.get('name', 'FAC')[:3].upper()),
                        'faculty': fac.get('name', ''),
                        'location': lab
                    })
                prac_cycle_idx += 1

            for slot_idx, slot in enumerate(time_slots):
                if slot['is_break']:
                    class_schedules[c_id][d][slot_idx] = {
                        'type': 'break',
                        'label': slot['label']
                    }
                elif slot_idx in prac_slots_today and today_batch_assignments:
                    # Parallel batch practical slot!
                    class_schedules[c_id][d][slot_idx] = {
                        'type': 'practical',
                        'batches': today_batch_assignments
                    }
                else:
                    # Theory lecture slot
                    fac = theory_faculty[theory_cycle_idx % len(theory_faculty)]
                    theory_cycle_idx += 1
                    class_schedules[c_id][d][slot_idx] = {
                        'type': 'theory',
                        'subject': fac.get('subject', '-'),
                        'abbr': fac.get('abbr', fac.get('name', 'FAC')[:3].upper()),
                        'faculty': fac.get('name', '-'),
                        'room': assigned_room
                    }

    # ── Calculate Workload Summary (matches bottom table of reference) ──
    workload_summary = []
    tot_lectures = 0
    tot_practicals = 0
    tot_all = 0

    for fac in faculty_list:
        th = fac.get('theory_hours', 0)
        ph = fac.get('practical_hours', 0)
        tot = th + ph
        tot_lectures += th
        tot_practicals += ph
        tot_all += tot
        workload_summary.append({
            'subject': fac.get('subject', '-'),
            'name': fac.get('name', '-'),
            'abbr': fac.get('abbr', fac.get('name', 'FAC')[:3].upper()),
            'theory_hours': th,
            'practical_hours': ph,
            'total_hours': tot,
            'batches': fac.get('practical_batches', [])
        })

    workload_totals = {
        'lectures': tot_lectures,
        'practicals': tot_practicals,
        'total': tot_all
    }

    return render_template(
        'timetable.html',
        config=config,
        time_slots=time_slots,
        schedules=class_schedules,
        active_batches=active_batches,
        workload_summary=workload_summary,
        workload_totals=workload_totals,
        primary_room=rooms[0] if rooms else "E102"
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
