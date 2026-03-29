## CSV Data Visualizer (Flask)

Signup/login, upload a CSV, choose a chart (bar/line/scatter/pie), visualize, and download PNG. Includes shared header/footer and a Team page.

### Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

Notes:
- SQLite DB at `app.db` created automatically
- Charts saved to `static/charts/`
- Set `FLASK_SECRET_KEY` to override default
