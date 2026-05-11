#!/usr/bin/env python3
"""
Amplitude Event Description Updater — GraphQL Edition
Run with: python3 final_app.py [--port 5001]
Then open: http://localhost:5001
"""

from flask import Flask, request, jsonify, render_template_string
import requests
from requests.auth import HTTPBasicAuth
import csv
import io
from datetime import datetime, timedelta

app = Flask(__name__)

GRAPHQL_URL = "https://app.amplitude.com/o/graphql"

# ─────────────────────────────────────────────
# GraphQL helpers
# ─────────────────────────────────────────────

def gql(api_key, secret_key, org_id, operation, query, variables):
    resp = requests.post(
        f"{GRAPHQL_URL}?q={operation}",
        auth=HTTPBasicAuth(api_key, secret_key),
        headers={"Content-Type": "application/json", "x-org": str(org_id)},
        json={"operationName": operation, "variables": variables, "query": query}
    )
    return resp


def get_branch_info(api_key, secret_key, org_id, workspace_id, branch_name):
    """Return (branch_id, version_id, error)."""
    q = """
    query Branches($orgId: ID!, $workspaceId: ID!) {
      orgs(id: $orgId) {
        workspaces(id: $workspaceId) {
          branches { id name currentVersionId }
        }
      }
    }
    """
    resp = gql(api_key, secret_key, org_id, "Branches", q,
               {"orgId": str(org_id), "workspaceId": workspace_id})

    if resp.status_code != 200:
        return None, None, f"Branches query failed (HTTP {resp.status_code}): {resp.text[:300]}"

    data = resp.json()
    if "errors" in data:
        return None, None, f"Branches query error: {data['errors'][0]['message']}"

    try:
        branches = data["data"]["orgs"][0]["workspaces"][0]["branches"]
    except (KeyError, IndexError):
        return None, None, f"Unexpected Branches response: {resp.text[:300]}"

    for b in branches:
        if b["name"] == branch_name:
            return b["id"], b["currentVersionId"], None

    names = [b["name"] for b in branches]
    return None, None, f"Branch '{branch_name}' not found. Available branches: {names}"


def get_events_map(api_key, secret_key, org_id, workspace_id, branch_id, version_id):
    """Return ({event_name: event_id}, error) for all events on the branch."""
    date_end   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    q = """
    query SimpleObservedEvents(
      $orgId: ID!, $workspaceId: ID!, $branchId: ID!,
      $versionId: ID!, $dateStart: DateTime!, $dateEnd: DateTime!, $branchName: String!
    ) {
      orgs(id: $orgId) {
        workspaces(id: $workspaceId) {
          branches(id: $branchId) {
            versions(id: $versionId, dateStart: $dateStart, dateEnd: $dateEnd, branchName: $branchName) {
              events(statuses: [live, planned, blocked, unexpected]) {
                id
                name
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "orgId":       str(org_id),
        "workspaceId": workspace_id,
        "branchId":    branch_id,
        "versionId":   version_id,
        "dateStart":   date_start,
        "dateEnd":     date_end,
        "branchName":  "main"
    }

    resp = gql(api_key, secret_key, org_id, "SimpleObservedEvents", q, variables)

    if resp.status_code != 200:
        return None, f"Events query failed (HTTP {resp.status_code}): {resp.text[:300]}"

    data = resp.json()
    if "errors" in data:
        return None, f"Events query error: {data['errors'][0]['message']}"

    try:
        events = data["data"]["orgs"][0]["workspaces"][0]["branches"][0]["versions"][0]["events"]
    except (KeyError, IndexError):
        return None, f"Could not parse events response: {resp.text[:300]}"

    return {e["name"]: e["id"] for e in events}, None


def edit_event(api_key, secret_key, org_id, event_id, description, version_id):
    """Run EditEvent mutation. Return (success, message)."""
    q = """
    mutation EditEvent($input: EditEventInput!) {
      editEvent(input: $input) {
        id
        description
        __typename
      }
    }
    """
    variables = {"input": {"id": event_id, "description": description, "versionId": version_id}}
    resp = gql(api_key, secret_key, org_id, "EditEvent", q, variables)

    if resp.status_code == 200:
        data = resp.json()
        if "errors" in data:
            return False, f"GraphQL error: {data['errors'][0]['message']}"
        return True, "Updated successfully"
    return False, f"EditEvent failed (HTTP {resp.status_code}): {resp.text[:300]}"


# ─────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Amplitude Event Updater</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f0f2f5;
      display: flex; justify-content: center; align-items: flex-start;
      min-height: 100vh; padding: 40px 16px;
    }
    .card {
      background: white; border-radius: 12px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
      width: 100%; max-width: 620px; overflow: hidden;
    }
    .card-header {
      background: linear-gradient(135deg, #1a1aff 0%, #6e40c9 100%);
      padding: 28px 32px; color: white;
    }
    .card-header h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
    .card-header p  { font-size: 13px; opacity: 0.8; }
    .card-body { padding: 32px; }

    .toggle-wrap {
      display: flex; background: #f0f2f5; border-radius: 8px;
      padding: 4px; margin-bottom: 28px;
    }
    .toggle-btn {
      flex: 1; padding: 9px 0; border: none; background: transparent;
      border-radius: 6px; font-size: 13px; font-weight: 600;
      color: #888; cursor: pointer; transition: all 0.2s;
    }
    .toggle-btn.active {
      background: white; color: #1a1aff;
      box-shadow: 0 1px 6px rgba(0,0,0,0.10);
    }

    .section { display: none; }
    .section.visible { display: block; }

    .section-title {
      font-size: 11px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.08em; color: #888; margin-bottom: 12px; margin-top: 24px;
    }
    .section-title:first-child { margin-top: 0; }
    .form-group { margin-bottom: 16px; }
    label { display: block; font-size: 13px; font-weight: 500; color: #444; margin-bottom: 6px; }

    input[type="text"], input[type="password"], textarea {
      width: 100%; padding: 10px 14px;
      border: 1.5px solid #e0e0e0; border-radius: 8px;
      font-size: 14px; color: #222; background: #fafafa;
      transition: border-color 0.2s, box-shadow 0.2s;
      outline: none; font-family: inherit;
    }
    input[type="text"]:focus, input[type="password"]:focus, textarea:focus {
      border-color: #1a1aff; box-shadow: 0 0 0 3px rgba(26,26,255,0.08); background: white;
    }
    textarea { resize: vertical; min-height: 90px; }

    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .grid-3 { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; }

    .toggle-secret { position: relative; }
    .toggle-secret input { padding-right: 40px; }
    .eye-btn {
      position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
      background: none; border: none; cursor: pointer; color: #aaa; font-size: 16px;
    }

    .drop-zone {
      border: 2px dashed #d0d0d0; border-radius: 10px; padding: 32px 20px;
      text-align: center; cursor: pointer; transition: border-color 0.2s, background 0.2s;
      background: #fafafa; position: relative;
    }
    .drop-zone:hover, .drop-zone.dragover { border-color: #1a1aff; background: #f0f0ff; }
    .drop-zone input[type="file"] {
      position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
    }
    .drop-icon  { font-size: 32px; margin-bottom: 8px; }
    .drop-label { font-size: 14px; font-weight: 600; color: #444; margin-bottom: 4px; }
    .drop-hint  { font-size: 12px; color: #999; }

    .file-chosen {
      display: none; align-items: center; gap: 10px;
      background: #f0f4ff; border: 1.5px solid #c0ccff;
      border-radius: 8px; padding: 10px 14px; margin-top: 10px;
      font-size: 13px; color: #333;
    }
    .file-chosen.visible { display: flex; }
    .file-name   { font-weight: 600; flex: 1; }
    .remove-file { background: none; border: none; cursor: pointer; color: #999; font-size: 18px; }
    .remove-file:hover { color: #e00; }

    .format-hint {
      background: #fffbeb; border: 1.5px solid #fde68a;
      border-radius: 8px; padding: 12px 14px; font-size: 12px;
      color: #92400e; margin-top: 12px; line-height: 1.6;
    }
    .format-hint strong { display: block; margin-bottom: 4px; font-size: 13px; }
    .format-hint code { background: #fef3c7; padding: 1px 5px; border-radius: 3px; font-family: monospace; }

    .btn {
      width: 100%; padding: 13px; border: none; border-radius: 8px;
      font-size: 15px; font-weight: 600; cursor: pointer;
      transition: opacity 0.2s, transform 0.1s; margin-top: 8px;
    }
    .btn-primary { background: linear-gradient(135deg, #1a1aff 0%, #6e40c9 100%); color: white; }
    .btn-primary:hover   { opacity: 0.9; }
    .btn-primary:active  { transform: scale(0.98); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

    .result {
      margin-top: 20px; border-radius: 8px; padding: 14px 16px;
      font-size: 13px; display: none;
    }
    .result.success { background: #f0fdf4; border: 1.5px solid #86efac; color: #166534; }
    .result.error   { background: #fef2f2; border: 1.5px solid #fca5a5; color: #991b1b; }
    .result.info    { background: #eff6ff; border: 1.5px solid #93c5fd; color: #1e40af; }
    .result.warning { background: #fffbeb; border: 1.5px solid #fde68a; color: #92400e; }
    .result-title   { font-weight: 700; margin-bottom: 6px; }

    .bulk-results { margin-top: 10px; max-height: 260px; overflow-y: auto; }
    .bulk-row {
      display: flex; align-items: flex-start; gap: 8px;
      padding: 6px 0; border-bottom: 1px solid rgba(0,0,0,0.06);
      font-size: 12px; line-height: 1.4;
    }
    .bulk-row:last-child { border-bottom: none; }
    .bulk-status { font-size: 14px; flex-shrink: 0; margin-top: 1px; }
    .bulk-event  { font-weight: 600; }
    .bulk-msg    { color: #666; }

    .progress-wrap {
      display: none; margin-top: 14px; background: #e5e7eb;
      border-radius: 99px; height: 6px; overflow: hidden;
    }
    .progress-bar {
      height: 100%;
      background: linear-gradient(135deg, #1a1aff, #6e40c9);
      border-radius: 99px; transition: width 0.3s ease; width: 0%;
    }
    .progress-label { font-size: 12px; color: #666; margin-top: 6px; text-align: center; display: none; }

    .spinner {
      display: inline-block; width: 14px; height: 14px;
      border: 2px solid rgba(255,255,255,0.4); border-top-color: white;
      border-radius: 50%; animation: spin 0.7s linear infinite;
      margin-right: 8px; vertical-align: middle;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .divider { border: none; border-top: 1px solid #f0f0f0; margin: 24px 0; }
  </style>
</head>
<body>
<div class="card">
  <div class="card-header">
    <h1>Amplitude Event Updater</h1>
    <p>Update event descriptions on a specific branch via GraphQL</p>
  </div>
  <div class="card-body">

    <div class="toggle-wrap">
      <button class="toggle-btn active" id="btn-single" onclick="setMode('single')">Single Event</button>
      <button class="toggle-btn"        id="btn-bulk"   onclick="setMode('bulk')">Bulk CSV Upload</button>
    </div>

    <!-- Credentials -->
    <div class="section-title">Credentials</div>
    <div class="grid-2">
      <div class="form-group">
        <label>API Key</label>
        <div class="toggle-secret">
          <input type="password" id="api_key" value="39191c427a0e6a09c2fb4860f68b3b3e" placeholder="API Key"/>
          <button class="eye-btn" onclick="toggleField('api_key')">👁</button>
        </div>
      </div>
      <div class="form-group">
        <label>Secret Key</label>
        <div class="toggle-secret">
          <input type="password" id="secret_key" value="b678fb73ddd89fa5746b0a85acd52a1d" placeholder="Secret Key"/>
          <button class="eye-btn" onclick="toggleField('secret_key')">👁</button>
        </div>
      </div>
    </div>

    <!-- Config -->
    <div class="section-title">Configuration</div>
    <div class="grid-2">
      <div class="form-group">
        <label>Org ID</label>
        <input type="text" id="org_id" value="64432" placeholder="e.g. 64432"/>
      </div>
      <div class="form-group">
        <label>Workspace ID</label>
        <input type="text" id="workspace_id" value="24342836-eaf8-4b26-bd6c-b2915b558614" placeholder="Workspace UUID"/>
      </div>
    </div>
    <div class="form-group">
      <label>Branch Name</label>
      <input type="text" id="branch" value="addEventsDescription" placeholder="e.g. addEventsDescription"/>
    </div>

    <hr class="divider"/>

    <!-- ── SINGLE MODE ── -->
    <div class="section visible" id="section-single">
      <div class="section-title" style="margin-top:0">Event</div>
      <div class="form-group">
        <label>Event Name</label>
        <input type="text" id="event_name" placeholder="e.g. user_clicked_on_kb_link"/>
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea id="description" placeholder="Enter the event description..."></textarea>
      </div>
      <button class="btn btn-primary" id="submitSingleBtn" onclick="submitSingle()">
        Update Event Description
      </button>
    </div>

    <!-- ── BULK MODE ── -->
    <div class="section" id="section-bulk">
      <div class="section-title" style="margin-top:0">Upload CSV</div>
      <div class="drop-zone" id="dropZone"
           ondragover="onDragOver(event)" ondragleave="onDragLeave(event)" ondrop="onDrop(event)">
        <input type="file" id="csvFile" accept=".csv" onchange="onFileChosen(event)"/>
        <div class="drop-icon">📄</div>
        <div class="drop-label">Drop your CSV here or click to browse</div>
        <div class="drop-hint">Accepted format: .csv</div>
      </div>
      <div class="file-chosen" id="fileChosen">
        <span style="font-size:20px">📄</span>
        <span class="file-name" id="fileName"></span>
        <button class="remove-file" onclick="clearFile()">✕</button>
      </div>
      <div class="format-hint">
        <strong>Required CSV format</strong>
        Your file must contain these exact column headers in row 1:<br/>
        <code>Event Name</code> &nbsp;|&nbsp; <code>Description</code><br/><br/>
        Example:<br/>
        <code>Event Name,Description</code><br/>
        <code>button_clicked,Fires when the user clicks a button</code>
      </div>
      <button class="btn btn-primary" id="submitBulkBtn" onclick="submitBulk()">
        Run Bulk Update
      </button>
      <div class="progress-wrap" id="progressWrap"><div class="progress-bar" id="progressBar"></div></div>
      <div class="progress-label" id="progressLabel"></div>
    </div>

    <!-- Result -->
    <div class="result" id="result">
      <div class="result-title" id="result-title"></div>
      <div id="result-msg"></div>
      <div class="bulk-results" id="bulk-results"></div>
    </div>

  </div>
</div>

<script>
  let currentFile = null;
  let currentMode = 'single';

  function setMode(mode) {
    currentMode = mode;
    document.getElementById('section-single').classList.toggle('visible', mode === 'single');
    document.getElementById('section-bulk').classList.toggle('visible', mode === 'bulk');
    document.getElementById('btn-single').classList.toggle('active', mode === 'single');
    document.getElementById('btn-bulk').classList.toggle('active', mode === 'bulk');
    hideResult();
  }

  function toggleField(id) {
    const i = document.getElementById(id);
    i.type = i.type === 'password' ? 'text' : 'password';
  }

  function getCreds() {
    return {
      api_key:      document.getElementById('api_key').value.trim(),
      secret_key:   document.getElementById('secret_key').value.trim(),
      org_id:       document.getElementById('org_id').value.trim(),
      workspace_id: document.getElementById('workspace_id').value.trim(),
      branch:       document.getElementById('branch').value.trim(),
    };
  }

  function onDragOver(e)  { e.preventDefault(); document.getElementById('dropZone').classList.add('dragover'); }
  function onDragLeave(e) { document.getElementById('dropZone').classList.remove('dragover'); }
  function onDrop(e) {
    e.preventDefault();
    document.getElementById('dropZone').classList.remove('dragover');
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  }
  function onFileChosen(e) { if (e.target.files[0]) setFile(e.target.files[0]); }
  function setFile(file) {
    currentFile = file;
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileChosen').classList.add('visible');
    hideResult();
  }
  function clearFile() {
    currentFile = null;
    document.getElementById('csvFile').value = '';
    document.getElementById('fileChosen').classList.remove('visible');
    hideResult();
  }

  function showResult(type, title, msg, rows) {
    const el = document.getElementById('result');
    el.className = 'result ' + type;
    el.style.display = 'block';
    document.getElementById('result-title').textContent = title;
    document.getElementById('result-msg').textContent   = msg;
    const bulkEl = document.getElementById('bulk-results');
    bulkEl.innerHTML = '';
    (rows || []).forEach(r => {
      const div = document.createElement('div');
      div.className = 'bulk-row';
      div.innerHTML = `<span class="bulk-status">${r.success ? '✅' : '❌'}</span>
        <div><div class="bulk-event">${r.event}</div><div class="bulk-msg">${r.message}</div></div>`;
      bulkEl.appendChild(div);
    });
  }
  function hideResult() { document.getElementById('result').style.display = 'none'; }

  function setProgress(pct, label) {
    document.getElementById('progressWrap').style.display  = 'block';
    document.getElementById('progressLabel').style.display = 'block';
    document.getElementById('progressBar').style.width     = pct + '%';
    document.getElementById('progressLabel').textContent   = label;
  }
  function hideProgress() {
    document.getElementById('progressWrap').style.display  = 'none';
    document.getElementById('progressLabel').style.display = 'none';
  }

  // ── Single submit ──
  async function submitSingle() {
    const creds      = getCreds();
    const event_name = document.getElementById('event_name').value.trim();
    const description= document.getElementById('description').value.trim();
    if (!creds.api_key || !creds.secret_key || !creds.branch || !event_name || !description) {
      showResult('error', 'Missing fields', 'Please fill in all fields.', []); return;
    }
    const btn = document.getElementById('submitSingleBtn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Updating…';
    showResult('info', 'Working…', 'Looking up branch and event, then updating…', []);
    try {
      const resp = await fetch('/update', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...creds, event_name, description})
      });
      const data = await resp.json();
      showResult(data.success ? 'success' : 'error',
        data.success ? '✓ Success' : '✗ Failed', data.message, []);
    } catch(e) { showResult('error', '✗ Error', 'Could not reach the server.', []); }
    btn.disabled = false; btn.innerHTML = 'Update Event Description';
  }

  // ── Bulk submit ──
  async function submitBulk() {
    const creds = getCreds();
    if (!creds.api_key || !creds.secret_key || !creds.branch) {
      showResult('error', 'Missing credentials', 'Please fill in all credential fields.', []); return;
    }
    if (!currentFile) {
      showResult('error', 'No file selected', 'Please upload a CSV file.', []); return;
    }
    const text = await currentFile.text();
    const vResp = await fetch('/validate_csv', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({csv_text: text})
    });
    const vData = await vResp.json();
    if (!vData.valid) { showResult('warning', '⚠ Invalid CSV', vData.message, []); return; }

    const rows  = vData.rows;
    const total = rows.length;
    const btn   = document.getElementById('submitBulkBtn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Processing…';
    setProgress(5, `Resolving branch and fetching events map…`);
    hideResult();

    let results = [];
    try {
      const resp = await fetch('/bulk_update', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...creds, rows})
      });
      const data = await resp.json();
      results = data.results || [];
      setProgress(100, `${total} / ${total} events processed`);
    } catch(e) {
      results = rows.map(r => ({event: r.event_name, success: false, message: 'Network error'}));
    }

    const succeeded = results.filter(r => r.success).length;
    const failed    = results.filter(r => !r.success).length;
    const type  = failed === 0 ? 'success' : succeeded === 0 ? 'error' : 'warning';
    const title = failed === 0 ? `✓ All ${total} events updated` : `${succeeded} succeeded · ${failed} failed`;
    showResult(type, title, '', results);
    btn.disabled = false; btn.innerHTML = 'Run Bulk Update';
    hideProgress();
  }
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/update", methods=["POST"])
def update_event():
    d            = request.json
    api_key      = d.get("api_key",      "").strip()
    secret_key   = d.get("secret_key",   "").strip()
    org_id       = d.get("org_id",       "").strip()
    workspace_id = d.get("workspace_id", "").strip()
    branch_name  = d.get("branch",       "").strip()
    event_name   = d.get("event_name",   "").strip()
    description  = d.get("description",  "").strip()

    # Step 1: get branch info
    branch_id, version_id, err = get_branch_info(api_key, secret_key, org_id, workspace_id, branch_name)
    if err:
        return jsonify({"success": False, "message": err})

    # Step 2: get event UUID
    events_map, err = get_events_map(api_key, secret_key, org_id, workspace_id, branch_id, version_id)
    if err:
        return jsonify({"success": False, "message": err})

    event_id = events_map.get(event_name)
    if not event_id:
        available = list(events_map.keys())[:5]
        return jsonify({"success": False,
                        "message": f"Event '{event_name}' not found on branch '{branch_name}'. "
                                   f"Sample available events: {available}"})

    # Step 3: edit event
    success, message = edit_event(api_key, secret_key, org_id, event_id, description, version_id)
    return jsonify({"success": success, "message": message})


@app.route("/bulk_update", methods=["POST"])
def bulk_update():
    d            = request.json
    api_key      = d.get("api_key",      "").strip()
    secret_key   = d.get("secret_key",   "").strip()
    org_id       = d.get("org_id",       "").strip()
    workspace_id = d.get("workspace_id", "").strip()
    branch_name  = d.get("branch",       "").strip()
    rows         = d.get("rows",         [])

    # Step 1: get branch info once
    branch_id, version_id, err = get_branch_info(api_key, secret_key, org_id, workspace_id, branch_name)
    if err:
        return jsonify({"results": [{"event": r.get("event_name",""), "success": False,
                                     "message": f"Branch lookup failed: {err}"} for r in rows]})

    # Step 2: get full events map once
    events_map, err = get_events_map(api_key, secret_key, org_id, workspace_id, branch_id, version_id)
    if err:
        return jsonify({"results": [{"event": r.get("event_name",""), "success": False,
                                     "message": f"Events fetch failed: {err}"} for r in rows]})

    # Step 3: fire EditEvent for each row
    results = []
    for row in rows:
        event_name  = row.get("event_name",  "").strip()
        description = row.get("description", "").strip()
        event_id    = events_map.get(event_name)
        if not event_id:
            results.append({"event": event_name, "success": False,
                            "message": f"Event not found on branch '{branch_name}'"})
            continue
        success, message = edit_event(api_key, secret_key, org_id, event_id, description, version_id)
        results.append({"event": event_name, "success": success, "message": message})

    return jsonify({"results": results})


@app.route("/validate_csv", methods=["POST"])
def validate_csv():
    csv_text = request.json.get("csv_text", "")
    try:
        reader  = csv.DictReader(io.StringIO(csv_text))
        headers = [h.strip() for h in (reader.fieldnames or [])]
        missing = []
        if "Event Name"  not in headers: missing.append('"Event Name"')
        if "Description" not in headers: missing.append('"Description"')
        if missing:
            return jsonify({"valid": False,
                            "message": f"Missing column(s): {' and '.join(missing)}.\n\n"
                                       "Required headers: Event Name, Description"})
        rows = [{"event_name": r.get("Event Name","").strip(),
                 "description": r.get("Description","").strip()}
                for r in reader
                if r.get("Event Name","").strip() and r.get("Description","").strip()]
        if not rows:
            return jsonify({"valid": False, "message": "No valid data rows found in the CSV."})
        return jsonify({"valid": True, "rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"valid": False, "message": f"Could not parse CSV: {e}"})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Amplitude Event Updater")
    parser.add_argument("--port", type=int, default=5001, help="Port to run on (default: 5001)")
    args = parser.parse_args()
    print("\n  Amplitude Event Updater — GraphQL Edition")
    print("  ──────────────────────────────────────────")
    print(f"  Open http://localhost:{args.port} in your browser\n")
    app.run(debug=False, port=args.port)
