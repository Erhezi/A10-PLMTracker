from app import create_app
from waitress import serve
import os   

# Get environment configuration
ENV = os.getenv('FLASK_ENV', 'development')
URL_PREFIX = os.getenv('URL_PREFIX', '/plmtracker' if ENV == 'production' else '')

# Create the application using our factory function
app = create_app(ENV)

if __name__ == '__main__':
    if ENV == 'production':
        print(f"Starting Waitress server in PRODUCTION mode with URL_PREFIX={URL_PREFIX}...")
        serve(app, host='0.0.0.0', port=8090)
    else:
        print(f"Starting Flask development server with URL_PREFIX={URL_PREFIX}...")

        print("Registered routes:")
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
            print(f"{rule} -> endpoint={rule.endpoint} methods=[{methods}]")
        app.run(debug=True)  # Use port 5060 for development