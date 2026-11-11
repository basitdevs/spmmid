"""Start the application and open it in the default browser."""
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from werkzeug.serving import make_server

from spms import create_app


def app_folder() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def free_port(preferred=5050) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def main():
    db_path = app_folder() / "spms.db"
    app = create_app(db_path)
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print("Smart Healthcare Project Management System")
    print(f"Running at {url}")
    print(f"Database: {db_path}")
    print("Close this window to stop the application.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    make_server("127.0.0.1", port, app, threaded=True).serve_forever()


if __name__ == "__main__":
    main()
