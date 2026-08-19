import os
import sys
import webbrowser
import threading
from time import sleep


def start_app():
    from app import create_app
    app = create_app()
    print("Starting library os on http://localhost:5000")

    def open_browser():
        sleep(2)
        webbrowser.open("http://localhost:5000")

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(debug=False, host="127.0.0.1", port=5000, use_reloader=False)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    try:
        import flask
        import flask_sqlalchemy
    except ImportError:
        print("Installing dependencies...")
        os.system(f'"{sys.executable}" -m pip install -r requirements.txt')

    start_app()