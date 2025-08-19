# Inventory Conversion Tracker (Skeleton)

Project scaffold generated from high-level design. Implementation to be added incrementally.

## Quick start

1. Create virtual environment (recommended `.venv`).
2. Install dependencies from `requirements.txt`.
3. Set required environment variables (see below) or copy `.env.example` to `.env` and edit.
4. Run the Flask app.

### Windows PowerShell example
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_APP = 'app'
$env:FLASK_ENV = 'development'
flask run
```

## Environment variables

Use a `.env` file for local development (it's ignored by git). Provide **placeholder / non-secret** values only in a tracked `.env.example` if/when created.

Suggested variables (expand as code is implemented):
- FLASK_SECRET_KEY
- DATABASE_URL (e.g. sqlite:///instance/app.db)
- MAIL_SERVER / credentials (if email verification needed)

## Contributing / workflow

- New features on feature branches; open PR into `main`.
- Keep commits small & descriptive.
- Run tests: `pytest -q` (add tests alongside new code).

## Git ignore

The `.gitignore` covers Python caches, virtual envs, logs, local databases, IDE files, and secrets. Do not commit real secrets or private keys.

## Next steps

- Flesh out models and services.
- Add tests for auth flow in `tests_auth_flow.py`.
- Create `.env.example` with safe placeholders.
