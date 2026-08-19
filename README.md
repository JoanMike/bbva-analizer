# BBVA Analizer

![License](https://img.shields.io/badge/license-PolyForm%20NC%201.0.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Web-orange)
![Flask](https://img.shields.io/badge/Flask-3.0-000000?logo=flask&logoColor=white)

> Local web app to analyze BBVA credit card statements in PDF format — split expenses between multiple people, manage assignments, and generate individual payment images.

## Overview

BBVA Analizer is a fully local Flask web application that parses BBVA credit card statement PDFs, extracts every transaction (installments and direct purchases), and lets you assign each expense to a person. Assignments are persisted in a SQLite database, and the app can generate 1080x1080 JPG payment images to share with each person.

## Features

- **Automatic data extraction** from BBVA statement PDFs.
- **Support for multiple BBVA formats** (legacy, 2026 tabular, and 2026+ narrative).
- **Automatic unlocking of password-protected PDFs** using a configured password.
- **Smart expense splitting** between people.
- **Automatic distribution of the "seguro desgravamen" insurance** across all users.
- **Assignment persistence** in a SQLite database, restored when the same statement is loaded again.
- **Clear transaction view** with installment information (`current of total`).
- **Description editing** with a replacement system applied to future transactions.
- **Dynamic people management** (add/remove users with name, icon, and color).
- **Payment image generation** (1080x1080 JPG) per person with a balance.
- **Portable executable** — no installation required (PyInstaller).

### Supported transaction types

| Type | Description | Example |
|------|-------------|---------|
| **Deferred installments** | Payments in installments with current/total info | `4 de 6` |
| **Direct purchases** | Purchases without installments paid in the month | `Directa` |
| **Seguro desgravamen** | Automatically distributed among people | `Seguro` |

## Tech Stack

- **Python 3.13+** with **Flask 3.0**.
- **pdfplumber** for PDF text extraction.
- **SQLite** for persistence; **Pillow** for payment image generation.
- **Vanilla JavaScript** frontend (no frameworks); CSS Grid and Flexbox.
- **PyInstaller** for the portable Windows executable.

## Requirements

- **From source:** Python 3.13 or higher and the dependencies in `requirements.txt`.
- **Compiled executable:** Windows 10/11 (64-bit), no additional dependencies.

## Installation

### Option 1: Run from source

```bash
git clone https://github.com/JoanMike/bbvaAnalizer.git
cd bbvaAnalizer
pip install -r requirements.txt
```

### Option 2: Portable executable (no installation)

```bash
build.bat
```

This generates `dist/start.exe`. Requires `pip install pyinstaller`.

## Configuration

### Password for protected PDFs

The app reads the password from an environment variable; no default password is included in the code.

1. Create your `.env` file from the example:

```bash
copy .env.example .env
```

2. Edit `.env` and set:

```env
PDF_UNLOCK_PASSWORD=your_password_here
```

`.env` location:

- **From source:** project root.
- **From the compiled executable:** next to `start.exe`.
- **If you run a local build in `dist/` inside the repo:** the project root `.env` is also accepted.

The `.env` file is git-ignored to avoid exposing secrets.

### Server port

Edit `config/settings.py`:

```python
FLASK_PORT = 5000  # change to another port
```

### Default people

Edit the `DEFAULT_PERSONAS` section in `config/settings.py`:

```python
DEFAULT_PERSONAS = [
    {'id': 'persona1', 'nombre': 'Persona 1', 'icono': '👤', 'color': '#1e88e5'},
    {'id': 'persona2', 'nombre': 'Persona 2', 'icono': '👤', 'color': '#43a047'},
    # Add more...
]
```

### Excluded concepts

To exclude certain transaction types, edit `CONCEPTOS_EXCLUIDOS` in `config/settings.py`:

```python
CONCEPTOS_EXCLUIDOS = [
    'SALDO CREDITO UTILIZADO MES ANTERIOR',
    'PAGO RECIBIDO',
    # Add more concepts...
]
```

## Usage

Start the app:

```bash
# Option A: startup script
python start.py

# Option B: batch file (Windows)
iniciar.bat
```

The app opens automatically in your browser at `http://localhost:5000`.

1. **Load a statement** — drag or select a BBVA PDF. The app automatically extracts general info (holder, card, period), all transactions (installments + direct purchases), and the financial summary.
2. **Seguro desgravamen split** — automatic: divided equally among all configured people; each person gets a separate transaction with their share.
3. **Assign transactions** — use the dropdown to assign each expense to a person. Filters: All, By person, Unassigned. Assignments are saved automatically.
4. **Edit descriptions** — click the edit button next to any transaction to create replacements applied automatically to future transactions with the same original description.
5. **Manage people** — "Gestionar Personas" button (bottom right): add new people (name, icon, color) or remove them (their assigned transactions become unassigned).
6. **Generate payment images** — "Generar Pagos" button downloads individual JPG images (1080x1080) for each person with a balance.
7. **Data persistence** — assignments are saved per PDF and restored when the same statement is reloaded. PDFs not accessed in over 90 days are cleaned up automatically.

## Advanced Usage

### Building the executable

```bash
build.bat
```

Executable characteristics:

- No console window (`--noconsole`).
- Single file (`--onefile`).
- Bundles all resources (templates, static, src, config). Application data (`data/`) is **never** bundled into the executable — it stays on your machine.
- Custom icon.
- Automatic file logging when run as .exe.

### When to rebuild

`dist/start.exe` is a generated PyInstaller artifact and does **not** update automatically. Run `build.bat` again whenever you change:

- Python code: `app.py`, `start.py`, `src/`, `config/`
- UI: `templates/`, `static/`
- Executable resources: `icon.ico`

To validate quick changes without rebuilding, run from source with `python start.py`.

## Project Structure

```text
bbvaAnalizer/
├── .env.example                    # Environment variable example
├── app.py                          # Main Flask application
├── start.py                        # Startup script
├── iniciar.bat                     # Windows launcher
├── build.bat                       # Build script
├── icon.ico                        # Executable icon
├── requirements.txt                # Python dependencies
├── config/                         # Centralized configuration
│   ├── __init__.py
│   └── settings.py                # Project constants and paths
├── src/                            # Business logic
│   ├── __init__.py
│   ├── database.py                # SQLite management
│   ├── pdf_parser.py              # PDF statement parsing
│   └── imaging.py                 # Payment image generation
├── tests/                          # Unit tests (unittest)
│   └── test_pdf_parser.py
├── data/                           # Application data
│   ├── personas.json              # User configuration
│   ├── description_replacements.json  # Custom replacements
│   └── bbva_analizer.db           # SQLite database
├── scripts/                        # Helper scripts
│   └── migrate_db.py              # Legacy data migration
├── static/                         # Frontend assets
│   ├── css/style.css
│   └── js/app.js
├── templates/                      # Flask HTML templates
│   └── index.html
├── uploads/                        # Temporary PDFs (auto-cleaned)
├── build/                          # Temporary build artifacts
└── dist/                           # Compiled executable (git-ignored)
    └── start.exe
```

## Notes

- **Database**: SQLite with `personas`, `description_replacements`, `pdfs`, and `transactions` tables; context manager for safe connections, automatic migration from legacy JSON files, and automatic cleanup of old data.
- **PDF format**: designed for BBVA statements; extracts general info, monthly installment details, monthly operations, and the financial summary. Installments are detected with the regex `(\d+)\s+de\s+(\d+)`.
- **Security and privacy**: 100% local app — no data is sent to external servers, temporary PDFs are deleted after processing, the database stays on your machine, and there is no telemetry.
- **Troubleshooting**: if the browser does not open, go to `http://localhost:5000` manually and check that port 5000 is free; if `dist/start.exe` behaves as before after code changes, rebuild with `build.bat`; logs for the .exe version are in `bbva_analizer.log`.
- **Tests**: run the unit test suite with `python -m unittest discover -s tests -v`.

## License

Distributed under the **PolyForm Noncommercial License 1.0.0** — free for
noncommercial use only. See [LICENSE](LICENSE) for the full license text.

Copyright (c) 2026 Jose Miguel Maldonado Garcia

## Author

**Jose Miguel Maldonado Garcia** — [@JoanMike](https://github.com/JoanMike)
