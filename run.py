import os
import sys

# Add project root and isolated libs to sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
libs_path = os.path.join(project_root, "libs")

for p in [project_root, libs_path]:
    if p not in sys.path:
        sys.path.insert(0, p)

from timetable_app import app

if __name__ == "__main__":
    print("Starting Timetable Management System...")
    print("Running on http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=True, use_reloader=False)
