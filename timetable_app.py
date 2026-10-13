import os
import sys

# Ensure isolated local libraries are loaded
_libs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs')
if os.path.exists(_libs_dir) and _libs_dir not in sys.path:
    sys.path.insert(0, _libs_dir)

import datetime
import random
from flask import Flask, render_template, request, session, redirect, url_for
from functools import wraps


app = Flask(__name__, template_folder='templates_2')
app.secret_key = os.environ.get('SECRET_KEY', 'default-timetable-secret-key-change-in-prod')

import json

# Persistent database storage path
FACULTY_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faculty_data.json')

# Remove any old database files if present (per user specification)
for _old_db in ['timetable.db', 'faculty.db', 'database.db', 'timetable.sqlite']:
    _old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _old_db)
    if os.path.exists(_old_path):
        try:
            os.remove(_old_path)
        except Exception:
            pass


def load_faculty():
    """Load faculty list from persistent JSON storage"""
    if not os.path.exists(FACULTY_DB_PATH):
        return []
    try:
        with open(FACULTY_DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_faculty(faculty_list):
    """Save faculty list to persistent JSON storage"""
    try:
        with open(FACULTY_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(faculty_list, f, indent=4)
        return True
    except Exception:
        return False


# Default credentials (in production, use a proper database)
VALID_CREDENTIALS = {
    'admin': 'admin',
    'user': 'password'
}


def login_required(f):
    """Decorator to protect routes that require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        # Validate credentials
        if username in VALID_CREDENTIALS and VALID_CREDENTIALS[username] == password:
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    # If already logged in, redirect to home
    if 'username' in session:
        return redirect(url_for('index'))
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Handle user logout"""
    session.clear()
    return redirect(url_for('login'))


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


@app.route('/faculty/add', methods=['POST'])
@login_required
def add_faculty():
    name = request.form.get('name', '').strip()
    subject = request.form.get('subject', '').strip()
    theory_hours = request.form.get('theory_hours', '3').strip()
    practical_hours = request.form.get('practical_hours', '1').strip()
    
    if name and subject:
        faculty_list = load_faculty()
        faculty_list.append({
            'name': name,
            'subject': subject,
            'theory_hours': int(theory_hours) if theory_hours.isdigit() else 3,
            'practical_hours': int(practical_hours) if practical_hours.isdigit() else 1
        })
        save_faculty(faculty_list)
        return render_template('faculty.html', faculty_list=faculty_list, message=f"Added '{name}' successfully!")
    return redirect(url_for('faculty_dashboard'))


@app.route('/faculty/delete/<int:index>', methods=['POST'])
@login_required
def delete_faculty(index):
    faculty_list = load_faculty()
    if 0 <= index < len(faculty_list):
        removed = faculty_list.pop(index)
        save_faculty(faculty_list)
        return render_template('faculty.html', faculty_list=faculty_list, message=f"Removed '{removed.get('name')}' successfully!")
    return redirect(url_for('faculty_dashboard'))


@app.route('/faculty/clear', methods=['POST'])
@login_required
def clear_faculty():
    save_faculty([])
    return render_template('faculty.html', faculty_list=[], message="All faculty records have been cleared.")


@app.route('/api/faculty/save-all', methods=['POST'])
@login_required
def api_save_all_faculty():
    data = request.get_json(silent=True)
    if data and isinstance(data.get('faculty'), list):
        clean_list = []
        for item in data['faculty']:
            name = str(item.get('name', '')).strip()
            subject = str(item.get('subject', '')).strip()
            if name or subject:
                th = item.get('theory_hours', 3)
                ph = item.get('practical_hours', 1)
                clean_list.append({
                    'name': name,
                    'subject': subject,
                    'theory_hours': int(th) if str(th).isdigit() else 3,
                    'practical_hours': int(ph) if str(ph).isdigit() else 1
                })
        save_faculty(clean_list)
        return {"status": "success", "count": len(clean_list)}
    return {"status": "error", "message": "Invalid payload"}, 400


@app.route('/generate', methods=['POST'])
@login_required
def generate():
    # Base Configuration
    config = {
        'start_time': request.form.get('start_time', '09:00'),
        'end_time': request.form.get('end_time', '16:00'),
        'lecture_duration': request.form.get('lecture_duration', '60'),
        'practical_duration': request.form.get('practical_duration', '90'),
        'num_classrooms': int(request.form.get('num_classrooms', '5')),
        'num_classes': int(request.form.get('num_classes', '2')),
        'num_labs': int(request.form.get('num_labs', '0')),
        'free_lectures': int(request.form.get('free_lectures', '0')),
        'working_days': request.form.getlist('working_days')
    }
   
    if not config['working_days']:
        config['working_days'] = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
       
    start = datetime.datetime.strptime(config['start_time'], '%H:%M')
    end = datetime.datetime.strptime(config['end_time'], '%H:%M')
    lec_dur = datetime.timedelta(minutes=int(config['lecture_duration']))


    # Parse Configured Faculty
    faculty_names = request.form.getlist('faculty_name[]')
    faculty_subjects = request.form.getlist('faculty_subject[]')
    faculty_hours = request.form.getlist('faculty_hours[]')
    faculty_practical_hours = request.form.getlist('faculty_practical_hours[]')
    
    faculty_list = []
    for n, s, h, ph in zip(faculty_names, faculty_subjects, faculty_hours, faculty_practical_hours):
        if n or s:
            faculty_list.append({
                "name": n,
                "subject": s,
                "theory_hours": int(h) if h else 0,
                "practical_hours": int(ph) if ph else 0
            })
    
    if faculty_list:
        save_faculty(faculty_list)
    else:
        faculty_list = [{"name": "Default Faculty", "subject": "General Study", "theory_hours": 4, "practical_hours": 0}]


    # Parse Configured Dynamic Breaks
    raw_starts = request.form.getlist('break_start[]')
    raw_ends = request.form.getlist('break_end[]')
    raw_labels = request.form.getlist('break_label[]')
    breaks = []
    for s, e, l in zip(raw_starts, raw_ends, raw_labels):
        if s and e:
            bs = datetime.datetime.strptime(s, '%H:%M')
            be = datetime.datetime.strptime(e, '%H:%M')
            breaks.append({"start": bs, "end": be, "label": l if l else "Break"})


    # ----------------------------------------------------
    # GENERATE TIME SLOTS (Slicing logic around breaks)
    # ----------------------------------------------------
    current_time = start
    time_slots = []
   
    while current_time < end:
        # Find if a break overlaps [current_time, current_time + lec_dur]
        next_break = None
        for b in breaks:
            if b['start'] <= current_time < b['end'] or current_time <= b['start'] < current_time + lec_dur:
                next_break = b
                break
               
        if next_break:
            if current_time >= next_break['start']:
                # We are inside the break
                time_slots.append({
                    "time": f"{current_time.strftime('%H:%M')} - {next_break['end'].strftime('%H:%M')}",
                    "is_break": True,
                    "label": next_break['label']
                })
                current_time = next_break['end']
            else:
                # We have time for a shortened lecture before the break hits
                slot_end = next_break['start']
                time_slots.append({
                    "time": f"{current_time.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                    "is_break": False
                })
                current_time = slot_end
        else:
            # Clean non-interrupted slot
            slot_end = current_time + lec_dur
            if slot_end > end:
                slot_end = end
               
            time_slots.append({
                "time": f"{current_time.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                "is_break": False
            })
            current_time = slot_end


    # ----------------------------------------------------
    # MULTI-CLASS SCHEDULING (Constraint Resolution)
    # ----------------------------------------------------
    class_ids = [f"Class/Section {i+1}" for i in range(config['num_classes'])]
    class_schedules = {c_id: {d: [] for d in config['working_days']} for c_id in class_ids}
   
    # Pre-calculate Free Lecture slots per class
    valid_coords = [(d, idx) for d in config['working_days'] for idx, s in enumerate(time_slots) if not s['is_break']]
    free_slots_map = {}
    for c_id in class_ids:
        # Pick unique random valid coords for off periods
        chosen_frees = random.sample(valid_coords, min(config['free_lectures'], len(valid_coords)))
        free_slots_map[c_id] = set(chosen_frees)


    # Available Resource pools
    rooms = [f"Room {101 + i}" for i in range(config['num_classrooms'])]
    if not rooms:
        rooms = ["Room A"]


    # Assign Slot by Slot globally ensuring NO duplicate assignments in a specific timeslot
    for slot_idx, slot in enumerate(time_slots):
        for d in config['working_days']:
           
            if slot['is_break']:
                # Everyone is on break
                for c_id in class_ids:
                    class_schedules[c_id][d].append(None)
            else:
                # Determine who needs a teacher this slot
                classes_needing_faculty = []
                for c_id in class_ids:
                    if (d, slot_idx) in free_slots_map[c_id]:
                        class_schedules[c_id][d].append({
                            "subject": "Free Time",
                            "faculty": "-",
                            "room": "-"
                        })
                    else:
                        classes_needing_faculty.append(c_id)
               
                # Shuffle distinct resources to pair randomly without overlap
                random.shuffle(faculty_list)
                random.shuffle(rooms)
               
                # Assign
                for i, c_id in enumerate(classes_needing_faculty):
                    if i < len(faculty_list):
                        fac = faculty_list[i]
                    else:
                        # Starvation: Not enough distinct faculty for parallel classes!
                        fac = {"name": "Conflict! Double Booked", "subject": "No Faculty"}
                       
                    if i < len(rooms):
                        room = rooms[i]
                    else:
                        room = "Conflict! No Room"
                       
                    class_schedules[c_id][d].append({
                        "subject": fac['subject'] if fac['subject'] else "-",
                        "faculty": fac['name'] if fac['name'] else "-",
                        "room": room
                    })


    return render_template('timetable.html', config=config, time_slots=time_slots, schedules=class_schedules)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)



