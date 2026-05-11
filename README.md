# Amplitude Event Updater — Setup & Run

## Requirements
- Python 3 installed ([python.org](https://www.python.org/downloads/) or via Homebrew: `brew install python`)

---

## Step 1 — Download the app
Place the `final_app.py` file in a folder on your computer (e.g. `~/Downloads/h8kton/`).

## Step 2 — Open Terminal and navigate to the folder
```bash
cd ~/Downloads/h8kton
```

## Step 3 — Create a virtual environment
```bash
python3 -m venv venv
```

## Step 4 — Activate the virtual environment
**macOS / Linux:**
```bash
source venv/bin/activate
```
**Windows:**
```bash
venv\Scripts\activate
```

## Step 5 — Install dependencies
```bash
pip install flask requests
```

## Step 6 — Run the app
```bash
python3 final_app.py
```

## Step 7 — Open in your browser
```
http://localhost:5001
```

---

## Next time (steps 1–3 already done)
```bash
cd ~/Downloads/h8kton
source venv/bin/activate   # (Windows: venv\Scripts\activate)
python3 final_app.py
```

To stop the app, press `Ctrl+C` in the terminal.
