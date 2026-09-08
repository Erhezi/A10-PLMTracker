from app import create_app
from waitress import serve
import os   
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound

# Get environment configuration
ENV = os.getenv('FLASK_ENV', 'development')
URL_PREFIX = os.getenv('URL_PREFIX', '/plm' if ENV == 'production' else '')

# Host/port are overridable, e.g.
#   PowerShell : $env:PORT=5001; python run.py
#   bash       : PORT=5001 python run.py
HOST = os.getenv('HOST', '0.0.0.0' if ENV == 'production' else '127.0.0.1')
_PORT_REQUESTED = os.getenv('PORT')
PORT = int(_PORT_REQUESTED or ('8090' if ENV == 'production' else '5000'))


def _port_is_free(host, port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # No SO_REUSEADDR here: we want to know if anyone actually holds it.
        return s.connect_ex(('127.0.0.1' if host == '0.0.0.0' else host, port)) != 0


def resolve_port(host, port, explicit):
    """Honour an explicit PORT; otherwise step past a port someone else holds.

    Being silently moved off a port you asked for is worse than failing, so an
    explicit PORT that is taken raises instead.
    """
    if _port_is_free(host, port):
        return port
    if explicit:
        raise SystemExit(
            f"Port {port} is already in use and PORT={port} was set explicitly.\n"
            f"Free it, or choose another:  $env:PORT=<n>; python run.py"
        )
    for candidate in range(port + 1, port + 21):
        if _port_is_free(host, candidate):
            print(f"Port {port} is in use (another app holds it) - using {candidate} instead.")
            print(f"Pin one with:  $env:PORT=<n>; python run.py")
            return candidate
    raise SystemExit(f"Ports {port}-{port + 20} are all in use.")

# Create the application using our factory function
app = create_app(ENV, URL_PREFIX)

if __name__ == '__main__':
    from app.config import Config

    # The debug reloader re-executes this file in a child process. Only the
    # parent picks a port; the child reuses it, or a reload could land on a
    # different port each time the code changes.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        port = PORT
    else:
        port = resolve_port(HOST, PORT, explicit=bool(_PORT_REQUESTED))
        os.environ['PORT'] = str(port)

    print(f"Database: {Config.describe_db()}")

    if ENV == 'production':
        print(f"Starting Waitress server in PRODUCTION mode with URL_PREFIX={URL_PREFIX}...")
        print(f"Listening on http://{HOST}:{port}{URL_PREFIX}")
        serve(app, host=HOST, port=port)
    else:
        print(f"Starting Flask development server with URL_PREFIX={URL_PREFIX}...")

        print("Registered routes:")
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
            print(f"{rule} -> endpoint={rule.endpoint} methods=[{methods}]")
        print(f"Listening on http://{HOST}:{port}{URL_PREFIX}")
        app.run(host=HOST, port=port, debug=True)