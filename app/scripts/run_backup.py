import os
import sys
import json

# Ensure project root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app, perform_backup

app = create_app()
with app.app_context():
    result = perform_backup()
    print(json.dumps(result))
