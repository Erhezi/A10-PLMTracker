from app import create_app
from waitress import serve
import os   
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound

# Get environment configuration
ENV = os.getenv('FLASK_ENV', 'development')
URL_PREFIX = os.getenv('URL_PREFIX', '/plm' if ENV == 'production' else '')

# Host/port are overridable so a second instance can run alongside one that
# already holds the default port:  PORT=5001 python run.py
HOST = os.getenv('HOST', '0.0.0.0' if ENV == 'production' else '127.0.0.1')
PORT = int(os.getenv('PORT', '8090' if ENV == 'production' else '5000'))

# Create the application using our factory function
app = create_app(ENV, URL_PREFIX)

if __name__ == '__main__':
    from app.config import Config
    print(f"Database: {Config.describe_db()}")

    if ENV == 'production':
        print(f"Starting Waitress server in PRODUCTION mode with URL_PREFIX={URL_PREFIX}...")
        print(f"Listening on http://{HOST}:{PORT}{URL_PREFIX}")
        serve(app, host=HOST, port=PORT)
    else:
        print(f"Starting Flask development server with URL_PREFIX={URL_PREFIX}...")

        print("Registered routes:")
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
            print(f"{rule} -> endpoint={rule.endpoint} methods=[{methods}]")
        print(f"Listening on http://{HOST}:{PORT}{URL_PREFIX}")
        app.run(host=HOST, port=PORT, debug=True)