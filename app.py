import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, send_file
from datetime import datetime, timedelta, timezone
import pandas as pd
import io
import os
import math

# ==========================================
# 1. CONFIGURATION
# ==========================================
app = Flask(__name__)
app.secret_key = 'secure_key_v38_pending_filter_sort'

# --- AUTO LOGOUT CONFIGURATION ---
app.permanent_session_lifetime = timedelta(minutes=15)

# --- FIREBASE SETUP START ---
# Fetching the variable from Railway Environment Variables
firebase_creds_json = os.getenv('FIREBASE_CONFIG')

if firebase_creds_json:
    try:
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("Firebase successfully initialized!")
    except Exception as e:
        print(f"Error parsing JSON or initializing Firebase: {e}")
else:
    print("CRITICAL ERROR: FIREBASE_CONFIG environment variable not found!")

db = firestore.client()
# --- FIREBASE SETUP END ---============
# 2. LOGIC & HELPERS
# ==========================================

def format_date_custom(value):
    if not value: return ""
    try: return datetime.strptime(value, '%Y-%m-%d').strftime('%d-%m-%y')
    except: return value 

def format_datetime_custom(value):
    if not value: return ""
    try:
        if isinstance(value, str):
            value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
        ist_time = value + timedelta(hours=5, minutes=30)
        return ist_time.strftime('%d-%m-%y %I:%M %p')
    except: return ""

app.jinja_env.filters['date_fmt'] = format_date_custom
app.jinja_env.filters['datetime_fmt'] = format_datetime_custom

def initialize_defaults():
    if not list(db.collection('users').where('username', '==', 'admin1').stream()):
        db.collection('users').add({'username': 'admin1', 'password': 'super', 'name': 'Super Administrator', 'role': 'SuperAdmin'})
    if not len(list(db.collection('units').limit(1).stream())):
        for u in ['KG', 'LTR', 'PCS', 'MTR', 'BOX']: db.collection('units').add({'name': u})
    if not len(list(db.collection('departments').limit(1).stream())):
        for d in ['HR', 'IT', 'ELECTRICAL', 'CTP', 'STORE']: db.collection('departments').add({'name': d})

initialize_defaults()

def get_financial_year_start():
    today = datetime.now()
    if today.month < 4: return datetime(today.year - 1, 4, 1)
    return datetime(today.year, 4, 1)

def get_next_serial_number(collection_name):
    start_date = get_financial_year_start()
    docs = db.collection(collection_name).where('created_at', '>=', start_date).stream()
    max_serial = 0
    for doc in docs:
        d = doc.to_dict()
        try:
            val = int(d.get('serial_no', 0))
            if val > max_serial: max_serial = val
        except: continue
    return max_serial + 1

def check_is_last_entry(collection_name, doc_id):
    curr = get_next_serial_number(collection_name) - 1
    doc = db.collection(collection_name).document(doc_id).get()
    if not doc.exists: return False
    try: return int(doc.to_dict().get('serial_no', 0)) == curr
    except: return False

def get_units_list():
    units = [doc.to_dict()['name'] for doc in db.collection('units').stream()]
    return sorted(list(set(units)))

def get_departments_list():
    depts = [doc.to_dict()['name'] for doc in db.collection('departments').stream()]
    return sorted(list(set(depts)))

def get_people_list():
    ppl = [doc.to_dict()['name'] for doc in db.collection('indent_persons').stream()]
    return sorted(list(set(ppl)))

def add_if_new(collection, name):
    if not name or name.lower() == 'other': return
    name = name.strip().upper()
    existing = list(db.collection(collection).where('name', '==', name).stream())
    if not existing:
        db.collection(collection).add({'name': name})

# ==========================================
# 3. HTML TEMPLATES (UPDATED WITH AUTO-LOGOUT SCRIPT)
# ==========================================

HTML_BASE_HEAD = """
<head>
    <meta charset="UTF-8">
    <title>DPPL Indent System</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.7.2/font/bootstrap-icons.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary-green: #2E8B57; /* SeaGreen */
            --dark-green: #1E5638;
            --light-green: #E8F5E9;
            --accent-green: #4CAF50;
        }
        body { font-family: 'Poppins', sans-serif; background-color: #f8f9fa; }
        .navbar-custom { background: linear-gradient(135deg, var(--dark-green), var(--primary-green)); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .navbar-brand { font-weight: 600; letter-spacing: 0.5px; }
        .navbar-custom .nav-link { color: rgba(255,255,255,0.9) !important; font-weight: 400; transition: all 0.3s; }
        .navbar-custom .nav-link:hover { color: #fff !important; transform: translateY(-1px); }
        .navbar-custom .nav-link.active { background-color: rgba(255,255,255,0.2) !important; border-radius: 6px; border: none !important; font-weight: 600; }
        .nav-tabs .nav-link { color: #000 !important; font-weight: 500; border: none; border-bottom: 3px solid transparent; background: transparent !important; }
        .nav-tabs .nav-link.active { color: var(--primary-green) !important; border-bottom: 3px solid var(--primary-green); font-weight: 600; }
        .card { border: none; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); overflow: hidden; }
        .card-header { background-color: var(--primary-green); color: white; font-weight: 500; border-bottom: none; padding: 15px 20px; }
        .table-hover tbody tr:hover { background-color: var(--light-green); }
        .table thead { background-color: var(--dark-green); color: white; }
        .status-received { background-color: #d1e7dd !important; color: #0f5132; }
        .btn-primary { background-color: var(--primary-green); border: none; }
        .btn-primary:hover { background-color: var(--dark-green); }
        .btn-success { background-color: var(--accent-green); border: none; }
        .text-green { color: var(--primary-green); }
        .small-meta { font-size: 0.75rem; color: #6c757d; line-height: 1.2; display: block; margin-top: 4px; }
        @media print { .no-print { display: none !important; } .card { box-shadow: none !important; border: 1px solid #ddd; } body { background-color: white !important; } }
    </style>
    
    <script>
        let idleTime = 0;
        $(document).ready(function () {
            // Increment the idle time counter every minute.
            setInterval(timerIncrement, 60000); // 1 minute

            // Zero the idle timer on any movement.
            $(this).mousemove(function (e) { idleTime = 0; });
            $(this).keypress(function (e) { idleTime = 0; });
            $(this).click(function (e) { idleTime = 0; });
        });

        function timerIncrement() {
            idleTime = idleTime + 1;
            if (idleTime >= 15) { // 15 minutes
                window.location.href = "/logout";
            }
        }
    </script>
    </head>
"""

HTML_NAV = """
<nav class="navbar navbar-expand-lg navbar-dark navbar-custom px-4 py-3 no-print">
    <span class="navbar-brand me-5"><i class="bi bi-tree-fill me-2"></i>DPPL Indent System</span>
    <div class="collapse navbar-collapse">
        <div class="nav nav-pills me-auto">
            <a href="{{ url_for('dashboard') }}" class="nav-link {% if system == 'indent' %}active{% endif %}">📦 Indent</a>
            <a href="{{ url_for('payment_dashboard') }}" class="nav-link {% if system == 'payment' %}active{% endif %}">💰 Payment</a>
        </div>
        <div class="text-light d-flex align-items-center">
            <span class="me-3"><small>Logged in as:</small> <strong>{{ session['user_name'] }}</strong> <span class="badge bg-light text-success rounded-pill">{{ session['role'] }}</span></span>
            {% if system == 'indent' %}
                <a href="{{ url_for('reports') }}" class="btn btn-sm btn-light text-success fw-bold me-2">Reports</a>
            {% elif system == 'payment' %}
                <a href="{{ url_for('payment_reports') }}" class="btn btn-sm btn-light text-success fw-bold me-2">Reports</a>
            {% endif %}
            {% if session['role'] in ['Admin', 'SuperAdmin'] %}
                <a href="{{ url_for('settings') }}" class="btn btn-sm btn-outline-light me-2"><i class="bi bi-gear-fill"></i></a>
            {% endif %}
            <a href="{{ url_for('logout') }}" class="btn btn-sm btn-danger rounded-pill px-3">Logout</a>
        </div>
    </div>
</nav>
"""

HTML_LOGIN = """
<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """
<body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh; background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);">
    <div class="card shadow-lg p-4" style="width: 380px; border-radius: 15px;">
        <div class="text-center mb-4">
            <h2 class="text-green fw-bold"><i class="bi bi-tree-fill"></i> DPPL</h2>
            <h5 class="text-muted">Indent System</h5>
        </div>
        {% with messages = get_flashed_messages() %}
            {% if messages %}<div class="alert alert-danger rounded-3">{{ messages[0] }}</div>{% endif %}
        {% endwith %}
        <form method="POST" action="{{ url_for('login') }}">
            <div class="form-floating mb-3">
                <input type="text" name="username" class="form-control" id="uInput" placeholder="Username" required>
                <label for="uInput">Username</label>
            </div>
            <div class="form-floating mb-3">
                <input type="password" name="password" class="form-control" id="pInput" placeholder="Password" required>
                <label for="pInput">Password</label>
            </div>
            <div class="form-check mb-3">
                <input class="form-check-input" type="checkbox" name="change_password" id="cpCheck">
                <label class="form-check-label small" for="cpCheck">I want to change my password</label>
            </div>
            <button type="submit" class="btn btn-primary w-100 py-2 rounded-3 fw-bold">Login</button>
        </form>
        <div class="text-center mt-3 small text-muted">&copy; 2026 DPPL Internal Systems</div>
    </div>
</body></html>
"""

HTML_CHANGE_PASS = """
<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """
<body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh;">
    <div class="card shadow p-4" style="width: 400px;">
        <h4 class="text-center mb-3 text-green">Change Password</h4>
        {% with messages = get_flashed_messages() %}
            {% if messages %}<div class="alert alert-info">{{ messages[0] }}</div>{% endif %}
        {% endwith %}
        <form method="POST">
            <div class="mb-2"><label>Username</label><input type="text" name="username" class="form-control" required></div>
            <div class="mb-2"><label>Old Password</label><input type="password" name="old_password" class="form-control" required></div>
            <div class="mb-3"><label>New Password</label><input type="password" name="new_password" class="form-control" required></div>
            <button type="submit" class="btn btn-success w-100">Update Password</button>
            <a href="{{ url_for('login') }}" class="btn btn-link w-100 mt-2 text-decoration-none text-muted">Back to Login</a>
        </form>
    </div>
</body></html>
"""

HTML_DASHBOARD_INDENT = """
<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """
<body>""" + HTML_NAV + """
<div class="container-fluid mt-4 px-4">
    <div class="d-flex justify-content-between align-items-center mb-4 no-print">
        <h3 class="text-green fw-bold">Indent Dashboard 
            {% if current_status == 'Pending' %}<span class="badge bg-warning text-dark ms-2" style="font-size: 0.5em; vertical-align: middle;">Pending Only</span>{% endif %}
        </h3>
        <div class="d-flex gap-2 align-items-center">
            <div class="btn-group shadow-sm me-2">
                <a href="{{ url_for('dashboard', status='All', search=request.args.get('search', '')) }}" 
                   class="btn btn-sm {{ 'btn-success' if current_status == 'All' else 'btn-outline-success' }}">All Items</a>
                <a href="{{ url_for('dashboard', status='Pending', search=request.args.get('search', '')) }}" 
                   class="btn btn-sm {{ 'btn-warning' if current_status == 'Pending' else 'btn-outline-warning' }}">
                   <i class="bi bi-clock-history"></i> Pending List
                </a>
            </div>

            <form method="GET" class="d-flex">
                <input type="hidden" name="status" value="{{ current_status }}">
                <div class="input-group">
                    <input type="text" name="search" class="form-control" placeholder="Search Item..." value="{{ request.args.get('search', '') }}">
                    <button class="btn btn-primary" type="submit"><i class="bi bi-search"></i></button>
                    {% if request.args.get('search') or current_status == 'Pending' %}
                    <a href="{{ url_for('dashboard') }}" class="btn btn-outline-secondary">Reset</a>
                    {% endif %}
                </div>
            </form>
            {% if session['role'] in ['Admin', 'SuperAdmin', 'Editor'] %}
                <a href="{{ url_for('create') }}" class="btn btn-success shadow-sm px-4"><i class="bi bi-plus-lg"></i> New Indent</a>
            {% endif %}
        </div>
    </div>
    <div class="card shadow">
        <div class="card-body p-0">
            {% if session['role'] in ['Admin', 'SuperAdmin'] %}
            <form id="bulkForm" method="POST" action="{{ url_for('bulk_update') }}">
                <div class="p-3 bg-light border-bottom no-print">
                    <div class="row g-2 align-items-end">
                        <div class="col-md-6 border-end pe-3">
                            <label class="small text-muted fw-bold text-uppercase mb-1">Approval Action</label>
                            <div class="input-group">
                                <span class="input-group-text bg-white border-end-0">By:</span>
                                <select name="approver_name" class="form-select border-start-0 ps-0">
                                    {% for u in users %}
                                        <option value="{{ u.name }}" {% if u.name == session['user_name'] %}selected{% endif %}>{{ u.name }}</option>
                                    {% endfor %}
                                </select>
                                <button type="submit" name="action" value="Approved" class="btn btn-success">Approve</button>
                                <button type="submit" name="action" value="Rejected" class="btn btn-danger">Reject</button>
                                <button type="submit" name="action" value="Pending" class="btn btn-secondary">Reset</button>
                            </div>
                        </div>
                        <div class="col-md-6 ps-3">
                            <label class="small text-muted fw-bold text-uppercase mb-1">Mark Received</label>
                            <div class="input-group">
                                <input type="date" name="bulk_received_date" class="form-control" value="{{ today }}">
                                <button type="submit" name="action" value="Received" class="btn btn-dark">Mark Selected Received</button>
                            </div>
                        </div>
                    </div>
                </div>
            {% endif %}
            
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead>
                        <tr>
                            {% if session['role'] in ['Admin', 'SuperAdmin'] %}
                            <th class="no-print text-center" style="width: 40px;"><input type="checkbox" onclick="toggleAll(this)"></th>
                            {% endif %}
                            <th>S.No</th>
                            <th>Date / Created By</th>
                            <th>Dept / Person</th>
                            <th>Item Details</th>
                            <th>Qty</th>
                            <th>Assigned</th>
                            <th>Approved By</th>
                            <th>Status</th>
                            <th>Received</th>
                            <th class="no-print">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for indent in indents %}
                        <tr class="{% if indent.received_status == 'Received' %}status-received{% endif %}">
                            {% if session['role'] in ['Admin', 'SuperAdmin'] %}
                            <td class="no-print text-center">
                                <input type="checkbox" name="selected_ids[]" value="{{ indent.id }}" class="row-checkbox" form="bulkForm">
                            </td>
                            {% endif %}
                            <td class="fw-bold text-secondary">{{ indent.serial_no }}</td>
                            <td>
                                <span class="fw-bold text-dark">{{ indent.indent_date | date_fmt }}</span>
                                <span class="small-meta text-muted">Cr: {{ indent.created_by }}<br>{{ indent.created_at | datetime_fmt }}</span>
                            </td>
                            <td><span class="d-block fw-500">{{ indent.department }}</span><span class="small text-muted">{{ indent.indent_person }}</span></td>
                            <td>
                                <strong class="text-green">{{ indent.item }}</strong>
                                {% if indent.reason %}<div class="small text-muted fst-italic">{{ indent.reason }}</div>{% endif %}
                                {% if indent.remarks %}<div class="small text-secondary mt-1"><i class="bi bi-chat-left-text me-1"></i>{{ indent.remarks }}</div>{% endif %}
                            </td>
                            <td class="fw-bold">{{ indent.quantity }} <span class="text-muted fw-normal">{{ indent.unit }}</span></td>
                            <td class="text-primary small fw-bold">{{ indent.assigned_to }}</td>
                            <td class="text-success small fw-bold">{{ indent.approved_by_name if indent.approved_by_name else '-' }}</td>
                            <td>
                                <span class="badge rounded-pill {% if indent.approval_status == 'Approved' %}bg-success{% elif indent.approval_status == 'Rejected' %}bg-danger{% else %}bg-warning text-dark{% endif %}">
                                    {{ indent.approval_status }}
                                </span>
                            </td>
                            <td>
                                {% if indent.received_status == 'Received' %}
                                    <span class="badge bg-primary">Received</span>
                                    <div class="small-meta">{{ indent.received_date | date_fmt }}</div>
                                {% else %}
                                    <span class="badge bg-light text-secondary border">Pending</span>
                                {% endif %}
                            </td>
                            <td class="no-print">
                                <div class="btn-group">
                                    {% if session['role'] in ['Admin', 'SuperAdmin', 'Editor'] %}
                                        <a href="{{ url_for('edit_indent', i_id=indent.id) }}" class="btn btn-sm btn-outline-primary border-0"><i class="bi bi-pencil-square"></i></a>
                                    {% endif %}
                                    {% if session['role'] in ['Admin', 'SuperAdmin'] %}
                                        <a href="{{ url_for('delete_indent', i_id=indent.id) }}" class="btn btn-sm btn-outline-danger border-0" onclick="return confirm('Delete?')"><i class="bi bi-trash"></i></a>
                                    {% endif %}
                                </div>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="12" class="text-center py-4 text-muted">No records found.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% if session['role'] in ['Admin', 'SuperAdmin'] %}</form>{% endif %}
            
            <div class="d-flex justify-content-between align-items-center p-3 bg-light border-top no-print">
                <div class="small text-muted">Page {{ page }}</div>
                <div>
                    {% if page > 1 %}
                    <a href="{{ url_for('dashboard', page=page-1, search=request.args.get('search', ''), status=current_status) }}" class="btn btn-sm btn-outline-secondary">Previous</a>
                    {% endif %}
                    {% if has_next %}
                    <a href="{{ url_for('dashboard', page=page+1, search=request.args.get('search', ''), status=current_status) }}" class="btn btn-sm btn-outline-secondary">Next</a>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>
<script>
    function toggleAll(source) {
        checkboxes = document.getElementsByClassName('row-checkbox');
        for(var i=0; i<checkboxes.length; i++) { checkboxes[i].checked = source.checked; }
    }
</script>
</body></html>
"""

HTML_CREATE_MULTI = """
<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body class="bg-light">""" + HTML_NAV + """
<div class="container mt-4">
    <div class="card shadow border-0">
        <div class="card-header bg-success text-white d-flex justify-content-between align-items-center">
            <h4 class="mb-0">Create Indent Batch</h4>
            <span class="badge bg-light text-success">Multiple Items</span>
        </div>
        <div class="card-body bg-white">
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}{% for category, message in messages %}<div class="alert alert-{{ category }} shadow-sm">{{ message }}</div>{% endfor %}{% endif %}
            {% endwith %}
            <form method="POST">
                <div class="row mb-4 p-3 bg-light border rounded-3 mx-0">
                    <div class="col-md-3"><label class="fw-bold small text-uppercase text-muted">Date</label><input type="date" name="indent_date" class="form-control" value="{{ today }}" required></div>
                    <div class="col-md-3"><label class="fw-bold small text-uppercase text-muted">Department</label><select name="department_select" class="form-select" onchange="checkDept(this)" required><option value="" disabled selected>Select Dept</option>{% for d in departments %}<option value="{{ d }}">{{ d }}</option>{% endfor %}<option value="Other">Other (Add New)</option></select><input type="text" name="custom_department" class="form-control mt-2 d-none" placeholder="Enter New Dept Name" id="customDeptInput"></div>
                    <div class="col-md-3"><label class="fw-bold small text-uppercase text-muted">Indent Person</label><input type="text" name="indent_person" list="personList" class="form-control" placeholder="Type name..."><datalist id="personList">{% for p in persons %}<option value="{{ p }}">{% endfor %}</datalist></div>
                    <div class="col-md-3"><label class="fw-bold small text-uppercase text-muted">Assign To</label><select name="assigned_to" class="form-select">{% for user in users %}<option value="{{ user.name }}">{{ user.name }}</option>{% endfor %}</select></div>
                </div>
                
                <h5 class="mb-3 text-green border-bottom pb-2">Item Details</h5>
                <table class="table table-bordered align-middle" id="itemsTable">
                    <thead class="table-light text-center"><tr><th width="20%">Item Name</th><th width="20%">Reason</th><th width="20%">Remarks</th><th width="10%">Qty</th><th width="20%">Unit</th><th width="5%"></th></tr></thead>
                    <tbody>
                        <tr>
                            <td><input type="text" name="item[]" class="form-control" required placeholder="Item Name"></td>
                            <td><input type="text" name="reason[]" class="form-control" placeholder="Why needed?"></td>
                            <td><input type="text" name="remarks[]" class="form-control" placeholder="Notes"></td>
                            <td><input type="number" name="quantity[]" class="form-control text-center" required></td>
                            <td>
                                <select name="unit[]" class="form-select unit-select" onchange="checkUnit(this)">{% for u in unit_list %}<option value="{{ u }}">{{ u }}</option>{% endfor %}<option value="Other">Other</option></select>
                                <input type="text" name="custom_unit[]" class="form-control mt-1 d-none custom-unit" placeholder="Unit">
                            </td>
                            <td class="text-center"><button type="button" class="btn btn-outline-danger btn-sm rounded-circle" onclick="removeRow(this)"><i class="bi bi-x-lg"></i></button></td>
                        </tr>
                    </tbody>
                </table>
                <div class="d-flex justify-content-between mt-3">
                    <button type="button" class="btn btn-outline-primary" onclick="addRow()"><i class="bi bi-plus-circle me-1"></i> Add Another Item</button>
                    <button type="submit" class="btn btn-success px-5 fw-bold shadow-sm">Submit Batch</button>
                </div>
            </form>
        </div>
    </div>
    {% if submitted_data %}
    <div class="card mt-4 border-success shadow-sm">
        <div class="card-header bg-light text-success fw-bold"><i class="bi bi-check-circle-fill me-2"></i> Recently Submitted Items</div>
        <div class="card-body p-0">
            <table class="table table-striped mb-0 small">
                <thead><tr><th>S.No</th><th>Dept</th><th>Item</th><th>Qty</th><th>Remarks</th><th>Assigned</th></tr></thead>
                <tbody>{% for d in submitted_data %}<tr><td class="fw-bold">{{ d.serial_no }}</td><td>{{ d.department }}</td><td>{{ d.item }}</td><td>{{ d.quantity }} {{ d.unit }}</td><td>{{ d.remarks }}</td><td>{{ d.assigned_to }}</td></tr>{% endfor %}</tbody>
            </table>
        </div>
    </div>
    {% endif %}
</div>
<script>
    function checkDept(selectObj){ var customInput = document.getElementById('customDeptInput'); if(selectObj.value === 'Other'){ customInput.classList.remove('d-none'); customInput.required = true; customInput.focus(); } else { customInput.classList.add('d-none'); customInput.required = false; } }
    function checkUnit(selectObj){ var customInput = selectObj.nextElementSibling; if(selectObj.value === 'Other'){ customInput.classList.remove('d-none'); customInput.required = true; } else { customInput.classList.add('d-none'); customInput.required = false; } }
    function addRow(){ var table = document.getElementById("itemsTable").getElementsByTagName('tbody')[0]; var newRow = table.rows[0].cloneNode(true); var inputs = newRow.getElementsByTagName('input'); for(var i=0; i<inputs.length; i++) inputs[i].value = ''; newRow.getElementsByClassName('custom-unit')[0].classList.add('d-none'); table.appendChild(newRow); }
    function removeRow(btn){ var table = document.getElementById("itemsTable").getElementsByTagName('tbody')[0]; if(table.rows.length > 1) btn.closest('tr').remove(); }
</script>
</body></html>
"""

HTML_EDIT = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body class="bg-light">""" + HTML_NAV + """<div class="container mt-5"><div class="card shadow mx-auto" style="max-width: 700px;"><div class="card-header"><h4>Edit Indent</h4></div><div class="card-body"><form method="POST"><div class="mb-3"><label>Serial Number (Locked)</label><input type="text" value="{{ data.serial_no }}" class="form-control" disabled></div>{% if session['role'] in ['Admin', 'SuperAdmin'] %}<div class="row mb-3"><div class="col-md-6"><div class="p-3 bg-warning bg-opacity-10 border border-warning rounded"><label class="fw-bold">Approval Status</label><select name="approval_status" class="form-select"><option value="Pending" {% if data.approval_status == 'Pending' %}selected{% endif %}>Pending</option><option value="Approved" {% if data.approval_status == 'Approved' %}selected{% endif %}>Approved</option><option value="Rejected" {% if data.approval_status == 'Rejected' %}selected{% endif %}>Rejected</option></select></div></div><div class="col-md-6"><div class="p-3 bg-info bg-opacity-10 border border-info rounded"><label class="fw-bold">Received Status</label><select name="received_status" class="form-select" id="recStatus" onchange="toggleRecDate()"><option value="Pending" {% if data.received_status != 'Received' %}selected{% endif %}>Pending</option><option value="Received" {% if data.received_status == 'Received' %}selected{% endif %}>Received</option></select><input type="date" name="received_date" id="recDate" class="form-control mt-2 {% if data.received_status != 'Received' %}d-none{% endif %}" value="{{ data.received_date }}"></div></div></div>{% endif %}<div class="row mb-3"><div class="col-md-4"><label>Date</label><input type="date" name="indent_date" class="form-control" value="{{ data.indent_date }}" required></div><div class="col-md-4"><label>Department</label><input type="text" name="department" class="form-control" value="{{ data.department }}" required list="deptList"><datalist id="deptList">{% for r in departments %}<option value="{{ r }}">{% endfor %}</datalist></div><div class="col-md-4"><label>Indent Person Name</label><input type="text" name="indent_person" class="form-control" value="{{ data.indent_person }}" list="personList"><datalist id="personList">{% for p in persons %}<option value="{{ p }}">{% endfor %}</datalist></div></div><div class="mb-3"><label>Item</label><input type="text" name="item" class="form-control" value="{{ data.item }}" required></div><div class="row mb-3"><div class="col-md-6"><label>Reason</label><input type="text" name="reason" class="form-control" value="{{ data.reason }}"></div><div class="col-md-6"><label>Remarks</label><input type="text" name="remarks" class="form-control" value="{{ data.remarks }}"></div></div><div class="row mb-3"><div class="col-md-4"><label>Quantity</label><input type="number" name="quantity" class="form-control" value="{{ data.quantity }}" required></div><div class="col-md-4"><label>Unit</label><select name="unit" class="form-select">{% for u in unit_list %}<option value="{{ u }}" {% if data.unit == u %}selected{% endif %}>{{ u }}</option>{% endfor %}</select></div><div class="col-md-4"><label>Assign To</label><select name="assigned_to" class="form-select">{% for user in users %}<option value="{{ user.name }}" {% if data.assigned_to == user.name %}selected{% endif %}>{{ user.name }}</option>{% endfor %}</select></div></div><button type="submit" class="btn btn-success w-100">Update</button></form></div></div></div><script>function toggleRecDate(){ var s = document.getElementById("recStatus").value; var d = document.getElementById("recDate"); if(s === "Received") d.classList.remove("d-none"); else d.classList.add("d-none"); }</script></body></html>"""
HTML_REPORTS = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body>""" + HTML_NAV + """<div class="container mt-4"><h3 class="mb-4 no-print text-green">Indent Reports</h3><div class="card shadow mb-4 no-print"><div class="card-body bg-light"><form method="POST" class="row g-3"><div class="col-md-2"><label>From</label><input type="date" name="start_date" class="form-control" value="{{ filters.start_date }}"></div><div class="col-md-2"><label>To</label><input type="date" name="end_date" class="form-control" value="{{ filters.end_date }}"></div><div class="col-md-2"><label>Department</label><input type="text" name="dept_filter" class="form-control" value="{{ filters.dept_filter }}"></div><div class="col-md-2"><label>Approval</label><select name="status" class="form-select"><option value="All">All</option><option value="Pending" {% if filters.status == 'Pending' %}selected{% endif %}>Pending</option><option value="Approved" {% if filters.status == 'Approved' %}selected{% endif %}>Approved</option><option value="Rejected" {% if filters.status == 'Rejected' %}selected{% endif %}>Rejected</option></select></div><div class="col-md-2"><label>Received</label><select name="received_status" class="form-select"><option value="All">All</option><option value="Received" {% if filters.received_status == 'Received' %}selected{% endif %}>Received</option><option value="Pending" {% if filters.received_status == 'Pending' %}selected{% endif %}>Pending Receipt</option></select></div><div class="col-md-2"><label>Assigned To</label><select name="assigned_filter" class="form-select"><option value="All">All</option>{% for u in users %}<option value="{{ u.name }}" {% if filters.assigned_filter == u.name %}selected{% endif %}>{{ u.name }}</option>{% endfor %}</select></div><div class="col-md-2"><label>Sort By</label><select name="sort_by" class="form-select"><option value="Date" {% if filters.sort_by == 'Date' %}selected{% endif %}>Date</option><option value="Department" {% if filters.sort_by == 'Department' %}selected{% endif %}>Department</option><option value="Assigned" {% if filters.sort_by == 'Assigned' %}selected{% endif %}>Assigned Person</option></select></div><div class="col-md-10 text-end"><button type="submit" name="action" value="filter" class="btn btn-primary px-4">Filter</button><button type="submit" name="action" value="export" class="btn btn-success px-4">Export Excel</button></div></form></div></div><div class="d-none d-print-block"><h2>Report</h2><p>{{ current_time | date_fmt }}</p></div><div class="card shadow"><div class="card-header bg-white d-flex justify-content-between align-items-center no-print"><h5>Results ({{ indents|length }})</h5><button onclick="window.print()" class="btn btn-dark">Print</button></div><div class="card-body"><table class="table table-bordered table-striped table-sm"><thead class="table-dark"><tr><th>S.No</th><th>Date</th><th>Dept</th><th>Person</th><th>Item</th><th>Qty</th><th>Remarks</th><th>Assigned</th><th>Approved By</th><th>Status</th><th>Received</th><th class="no-print">Actions</th></tr></thead><tbody>{% for indent in indents %}<tr><td>{{ indent.serial_no }}</td><td>{{ indent.indent_date | date_fmt }}</td><td>{{ indent.department }}</td><td>{{ indent.indent_person }}</td><td>{{ indent.item }}</td><td>{{ indent.quantity }} {{ indent.unit }}</td><td>{{ indent.remarks }}</td><td>{{ indent.assigned_to }}</td><td>{{ indent.approved_by_name if indent.approved_by_name else '' }}</td><td>{{ indent.approval_status }}</td><td>{% if indent.received_status == 'Received' %}Received ({{ indent.received_date | date_fmt }}){% else %}Pending{% endif %}</td><td class="no-print">{% if session['role'] in ['Admin', 'SuperAdmin', 'Editor'] %}<a href="{{ url_for('edit_indent', i_id=indent.id) }}" class="btn btn-sm btn-outline-primary py-0">Edit</a>{% endif %}{% if session['role'] in ['Admin', 'SuperAdmin'] %}<a href="{{ url_for('delete_indent', i_id=indent.id) }}" class="btn btn-sm btn-outline-danger py-0" onclick="return confirm('Delete?')">Del</a>{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div></body></html>"""
HTML_CREATE_PAYMENT = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body class="bg-light">""" + HTML_NAV + """<div class="container mt-5"><div class="card shadow mx-auto" style="max-width: 800px;"><div class="card-header"><h4>New Payment / Order</h4></div><div class="card-body"><ul class="nav nav-tabs mb-4" id="paymentTabs"><li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#regularBill" onclick="setMode('Bill')">Regular Bill Entry</a></li><li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#advanceOrder" onclick="setMode('Advance')">Advance / PO Entry</a></li></ul><form method="POST"><input type="hidden" name="entry_type" id="entryType" value="Bill"><div class="tab-content"><div class="tab-pane fade show active" id="regularBill"><div class="mb-3"><label class="fw-bold">Party Name</label><input type="text" name="party_name" class="form-control" placeholder="Vendor Name"></div><div class="row mb-3"><div class="col-md-6"><label class="fw-bold">Bill Number</label><input type="text" name="bill_number" class="form-control"></div><div class="col-md-6"><label class="fw-bold">Bill Date</label><input type="date" name="bill_date" class="form-control" value="{{ today }}"></div></div><div class="row mb-3"><div class="col-md-6"><label class="fw-bold">Amount</label><input type="number" step="0.01" name="amount" class="form-control"></div><div class="col-md-6"><label class="fw-bold">Due Date</label><input type="date" name="due_date" class="form-control"></div></div></div><div class="tab-pane fade" id="advanceOrder"><div class="row mb-3"><div class="col-md-6"><label class="fw-bold">Party Name</label><input type="text" name="adv_party_name" class="form-control"></div><div class="col-md-6"><label class="fw-bold">Quotation No.</label><input type="text" name="quotation_no" class="form-control"></div></div><div class="p-3 bg-light border rounded mb-3"><h6 class="text-primary">Product Details</h6><div class="mb-2"><label>Product Name / Detail</label><input type="text" name="item_detail" class="form-control"></div><div class="row"><div class="col-md-3"><label>Qty</label><input type="number" step="0.01" name="qty" id="qty" class="form-control" oninput="calcTotal()"></div><div class="col-md-3"><label>Price</label><input type="number" step="0.01" name="price" id="price" class="form-control" oninput="calcTotal()"></div><div class="col-md-3"><label>Tax</label><input type="number" step="0.01" name="tax" id="tax" class="form-control" oninput="calcTotal()" value="0"></div><div class="col-md-3"><label>Freight</label><input type="number" step="0.01" name="freight" id="freight" class="form-control" oninput="calcTotal()" value="0"></div></div><div class="mt-2 text-end"><h5>Total: <span id="totalDisplay">0.00</span></h5><input type="hidden" name="adv_amount" id="advAmount"></div></div><div class="row mb-3"><div class="col-md-6"><label class="fw-bold">Payment Type</label><select name="payment_type" class="form-select" onchange="toggleBank(this)"><option value="Credit">Credit</option><option value="Advance">Advance</option></select></div><div class="col-md-6"><label class="fw-bold">Delivery Time</label><input type="text" name="delivery_time" class="form-control" placeholder="e.g. 7 Days"></div></div><div id="bankDetails" class="d-none p-3 border border-warning rounded bg-warning bg-opacity-10 mb-3"><h6>Bank Details (Required for Advance)</h6><div class="row"><div class="col-md-3"><label class="small fw-bold">Bank Name</label><input type="text" name="bank_name" class="form-control" placeholder="Bank Name"></div><div class="col-md-3"><label class="small fw-bold">Branch Name</label><input type="text" name="branch_name" class="form-control" placeholder="Branch"></div><div class="col-md-3"><label class="small fw-bold">Account No</label><input type="text" name="account_no" class="form-control" placeholder="Account No"></div><div class="col-md-3"><label class="small fw-bold">IFSC Code</label><input type="text" name="ifsc" class="form-control" placeholder="IFSC Code"></div></div></div></div></div><div class="mb-3 mt-3"><label class="fw-bold">Approved By</label><input type="text" name="approved_by" class="form-control" required placeholder="Enter Name"></div><button type="submit" class="btn btn-success w-100">Save Entry</button><a href="{{ url_for('payment_dashboard') }}" class="btn btn-secondary w-100 mt-2">Cancel</a></form></div></div></div><script>function setMode(mode){document.getElementById('entryType').value=mode;}function toggleBank(select){var bankDiv=document.getElementById('bankDetails');if(select.value==='Advance')bankDiv.classList.remove('d-none');else bankDiv.classList.add('d-none');}function calcTotal(){var qty=parseFloat(document.getElementById('qty').value)||0;var price=parseFloat(document.getElementById('price').value)||0;var tax=parseFloat(document.getElementById('tax').value)||0;var freight=parseFloat(document.getElementById('freight').value)||0;var total=(qty*price)+tax+freight;document.getElementById('totalDisplay').innerText=total.toFixed(2);document.getElementById('advAmount').value=total.toFixed(2);}</script></body></html>"""
HTML_EDIT_PAYMENT = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body class="bg-light">""" + HTML_NAV + """<div class="container mt-5"><div class="card shadow mx-auto" style="max-width: 700px;"><div class="card-header"><h4>Edit Payment</h4></div><div class="card-body"><form method="POST"><div class="mb-3"><label>Serial Number</label><input type="text" value="{{ data.serial_no }}" class="form-control" disabled></div>{% if data.type == 'Advance' %}<div class="alert alert-info">Advance Order Entry</div><div class="row mb-2"><div class="col-md-6"><label>Party Name</label><input type="text" name="party_name" class="form-control" value="{{ data.party_name }}"></div><div class="col-md-6"><label>Quotation No</label><input type="text" name="quotation_no" class="form-control" value="{{ data.quotation_no }}"></div></div><div class="row mb-2"><div class="col-md-6"><label>Item</label><input type="text" name="item_detail" class="form-control" value="{{ data.item_detail }}"></div><div class="col-md-6"><label>Amount</label><input type="number" step="0.01" name="amount" class="form-control" value="{{ data.amount }}"></div></div><div class="row mb-2"><div class="col-md-4"><label>Qty</label><input type="text" name="qty" class="form-control" value="{{ data.qty }}"></div><div class="col-md-4"><label>Price</label><input type="text" name="price" class="form-control" value="{{ data.price }}"></div><div class="col-md-4"><label>Tax</label><input type="text" name="tax" class="form-control" value="{{ data.tax }}"></div></div><div class="row mb-2"><div class="col-md-6"><label>Payment Type</label><input type="text" name="payment_type" class="form-control" value="{{ data.payment_type }}"></div><div class="col-md-6"><label>Delivery Time</label><input type="text" name="delivery_time" class="form-control" value="{{ data.delivery_time }}"></div></div><div class="mb-2"><label>Bank Details</label><input type="text" name="bank_details" class="form-control" value="{{ data.bank_details }}"></div>{% else %}<div class="alert alert-secondary">Regular Bill Entry</div><div class="row mb-3"><div class="col-md-12 mb-2"><label class="fw-bold">Party Name</label><input type="text" name="party_name" class="form-control" value="{{ data.party_name }}" required></div><div class="col-md-6 mb-2"><label class="fw-bold">Bill Number</label><input type="text" name="bill_number" class="form-control" value="{{ data.bill_number }}" required></div><div class="col-md-6 mb-2"><label class="fw-bold">Bill Date</label><input type="date" name="bill_date" class="form-control" value="{{ data.bill_date }}" required></div><div class="col-md-6"><label class="fw-bold">Amount</label><input type="number" step="0.01" name="amount" class="form-control" value="{{ data.amount }}" required></div><div class="col-md-6"><label class="fw-bold">Due Date</label><input type="date" name="due_date" class="form-control" value="{{ data.due_date }}" required></div></div>{% endif %}<div class="col-md-12 mt-2"><label class="fw-bold">Approved By (Manual)</label><input type="text" name="approved_by" class="form-control" value="{{ data.approved_by }}" required></div><div class="mb-3 mt-3 p-3 border rounded border-warning bg-warning bg-opacity-10"><h5 class="text-dark">Status & Payment</h5><div class="mb-3"><label class="fw-bold">Status</label><select name="status" class="form-select" id="statusSelect" onchange="toggleDetails()"><option value="Pending" {% if data.status == 'Pending' %}selected{% endif %}>Pending</option><option value="Done" {% if data.status == 'Done' %}selected{% endif %}>Done (Paid)</option></select></div><div id="paymentDetails" class="{% if data.status != 'Done' %}d-none{% endif %}"><div class="row"><div class="col-md-6 mb-2"><label class="fw-bold">Payment Date</label><input type="date" name="payment_date" class="form-control" value="{{ data.payment_date }}"></div><div class="col-md-6 mb-2"><label class="fw-bold">Mode</label><select name="payment_mode" class="form-select"><option value="" selected disabled>Select</option><option value="NEFT" {% if data.payment_mode == 'NEFT' %}selected{% endif %}>NEFT</option><option value="RTGS" {% if data.payment_mode == 'RTGS' %}selected{% endif %}>RTGS</option><option value="UPI" {% if data.payment_mode == 'UPI' %}selected{% endif %}>UPI</option><option value="CHEQUE" {% if data.payment_mode == 'CHEQUE' %}selected{% endif %}>CHEQUE</option><option value="CASH" {% if data.payment_mode == 'CASH' %}selected{% endif %}>CASH</option></select></div><div class="col-md-12"><label class="fw-bold">Ref No.</label><input type="text" name="transaction_ref" class="form-control" value="{{ data.transaction_ref }}"></div></div></div></div><button type="submit" class="btn btn-success w-100">Update</button><a href="{{ url_for('payment_dashboard') }}" class="btn btn-secondary w-100 mt-2">Cancel</a></form></div></div></div><script>function toggleDetails(){var status=document.getElementById("statusSelect").value;var detailsDiv=document.getElementById("paymentDetails");if(status==="Done")detailsDiv.classList.remove("d-none");else detailsDiv.classList.add("d-none");}</script></body></html>"""
HTML_DASHBOARD_PAYMENT = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body>""" + HTML_NAV + """<div class="container-fluid mt-4 px-4"><div class="d-flex justify-content-between align-items-center mb-3 no-print"><h3 class="text-green fw-bold">Payment System</h3>{% if session['role'] in ['Admin', 'SuperAdmin', 'Editor'] %}<a href="{{ url_for('create_payment') }}" class="btn btn-success">+ New Payment Entry</a>{% endif %}</div><div class="card shadow"><div class="card-body"><table class="table table-hover table-bordered align-middle table-sm"><thead class="table-light"><tr><th>SR.NO</th><th>TYPE</th><th>PARTY NAME</th><th>DETAILS</th><th>AMOUNT</th><th>APPROVED BY</th><th>STATUS</th><th class="no-print">ACTIONS</th></tr></thead><tbody>{% for p in payments %}<tr><td class="fw-bold">{{ p.serial_no }}</td><td>{% if p.type == 'Advance' %}<span class="badge bg-info text-dark">Advance/PO</span>{% else %}<span class="badge bg-secondary">Bill</span>{% endif %}</td><td>{{ p.party_name }}</td><td>{% if p.type == 'Advance' %}Qt: {{ p.quotation_no }} | {{ p.item_detail }}<br><span class="text-muted small">Delivery: {{ p.delivery_time }}</span>{% else %}Bill: {{ p.bill_number }}<br><span class="text-muted small">Due: {{ p.due_date | date_fmt }}</span>{% endif %}</td><td class="fw-bold text-end">{{ p.amount }}</td><td>{{ p.approved_by }}</td><td>{% if p.status == 'Done' %}<span class="badge bg-success">Done</span>{% else %}<span class="badge bg-danger">Pending</span>{% endif %}</td><td class="no-print">{% if session['role'] in ['Admin', 'SuperAdmin', 'Editor'] %}<a href="{{ url_for('edit_payment', p_id=p.id) }}" class="btn btn-sm btn-outline-primary"><i class="bi bi-pencil-square"></i></a>{% endif %}{% if session['role'] in ['Admin', 'SuperAdmin'] %}<a href="{{ url_for('delete_payment', p_id=p.id) }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?')"><i class="bi bi-trash"></i></a>{% endif %}</td></tr>{% else %}<tr><td colspan="8" class="text-center">No payment records found.</td></tr>{% endfor %}</tbody></table></div></div></div></body></html>"""
HTML_REPORTS_PAYMENT = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body>""" + HTML_NAV + """<div class="container mt-4"><h3 class="mb-4 no-print text-green">Payment Reports</h3><div class="card shadow mb-4 no-print"><div class="card-body bg-light"><form method="POST" class="row g-3"><div class="col-md-2"><label>From</label><input type="date" name="start_date" class="form-control" value="{{ filters.start_date }}"></div><div class="col-md-2"><label>To</label><input type="date" name="end_date" class="form-control" value="{{ filters.end_date }}"></div><div class="col-md-2"><label>Party Name</label><input type="text" name="party_filter" class="form-control" value="{{ filters.party_filter }}"></div><div class="col-md-2"><label>Status</label><select name="status" class="form-select"><option value="All">All</option><option value="Pending" {% if filters.status == 'Pending' %}selected{% endif %}>Pending</option><option value="Done" {% if filters.status == 'Done' %}selected{% endif %}>Done</option></select></div><div class="col-md-2 d-flex align-items-end gap-2"><button type="submit" name="action" value="filter" class="btn btn-primary w-50">Filter</button><button type="submit" name="action" value="export" class="btn btn-success w-50">Excel</button></div></form></div></div><div class="d-none d-print-block"><h2>Payment Report</h2><p>{{ current_time | date_fmt }}</p></div><div class="card shadow"><div class="card-header bg-white d-flex justify-content-between align-items-center no-print"><h5>Results ({{ payments|length }})</h5><button onclick="window.print()" class="btn btn-dark">Print</button></div><div class="card-body"><table class="table table-bordered table-striped table-sm align-middle"><thead class="table-dark"><tr><th>SR</th><th>TYPE</th><th>PARTY</th><th>REF/BILL</th><th>ITEM/DETAILS</th><th>AMOUNT</th><th>STATUS</th></tr></thead><tbody>{% for p in payments %}<tr><td>{{ p.serial_no }}</td><td>{{ p.type }}</td><td>{{ p.party_name }}</td><td>{% if p.type == 'Advance' %}Qt: {{ p.quotation_no }}{% else %}Bill: {{ p.bill_number }}{% endif %}</td><td>{% if p.type == 'Advance' %}{{ p.item_detail }} (Qty: {{ p.qty }}){% else %}Bill Date: {{ p.bill_date | date_fmt }}{% endif %}</td><td>{{ p.amount }}</td><td>{{ p.status }}</td></tr>{% endfor %}</tbody></table></div></div></div></body></html>"""
HTML_SETTINGS = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body>""" + HTML_NAV + """<div class="container mt-4"><h2 class="mb-4 text-green">Admin Settings</h2><ul class="nav nav-tabs" id="myTab" role="tablist"><li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#units">Manage Units</button></li><li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#users">Manage Users</button></li><li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#logs">Login Logs</button></li></ul><div class="tab-content pt-4"><div class="tab-pane fade show active" id="units"><div class="row"><div class="col-md-5"><div class="card shadow"><div class="card-header bg-secondary text-white">Add New Unit</div><div class="card-body"><form method="POST" action="{{ url_for('add_unit') }}"><div class="input-group"><input type="text" name="unit_name" class="form-control" placeholder="e.g. PACKET" required><button class="btn btn-success" type="submit">Add</button></div></form></div></div></div><div class="col-md-7"><div class="card shadow"><div class="card-header">Existing Units</div><div class="card-body"><table class="table table-sm"><thead><tr><th>Unit Name</th><th>Action</th></tr></thead><tbody>{% for u in units %}<tr><td>{{ u.name }}</td><td><a href="{{ url_for('delete_unit', uid=u.id) }}" class="btn btn-sm btn-outline-danger">Delete</a></td></tr>{% endfor %}</tbody></table></div></div></div></div></div><div class="tab-pane fade" id="users"><div class="d-flex justify-content-end mb-2"><a href="{{ url_for('edit_user', uid='new') }}" class="btn btn-success">+ Create User</a></div><div class="card shadow"><div class="card-body"><table class="table"><thead class="table-dark"><tr><th>Name</th><th>Username</th><th>Role</th><th>Password</th><th>Actions</th></tr></thead><tbody>{% for user in users %}<tr><td>{{ user.name }}</td><td>{{ user.username }}</td><td>{{ user.role }}</td><td class="font-monospace">{% if session['role'] == 'SuperAdmin' %}<span class="text-danger">{{ user.password }}</span>{% else %}******{% endif %}</td><td><a href="{{ url_for('edit_user', uid=user.id) }}" class="btn btn-sm btn-primary">Edit</a>{% if session['role'] == 'SuperAdmin' %}<a href="{{ url_for('delete_user', uid=user.id) }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</a>{% elif session['role'] == 'Admin' and user.role not in ['Admin', 'SuperAdmin'] %}<a href="{{ url_for('delete_user', uid=user.id) }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</a>{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div><div class="tab-pane fade" id="logs"><div class="card shadow"><div class="card-header bg-info text-white">Recent Logins (Last 50)</div><div class="card-body">{% if session['role'] == 'SuperAdmin' %}<table class="table table-striped table-sm"><thead><tr><th>Time</th><th>Name</th><th>Username</th><th>Role</th></tr></thead><tbody>{% for log in logs %}<tr><td>{{ log.timestamp | datetime_fmt }}</td><td>{{ log.name }}</td><td>{{ log.username }}</td><td>{{ log.role }}</td></tr>{% else %}<tr><td colspan="4" class="text-center">No logs found</td></tr>{% endfor %}</tbody></table>{% else %}<div class="alert alert-warning text-center">Only SuperAdmin can view logs.</div>{% endif %}</div></div></div></div></div><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script></body></html>"""
HTML_EDIT_USER = """<!DOCTYPE html><html lang="en">""" + HTML_BASE_HEAD + """<body class="bg-light">""" + HTML_NAV + """<div class="container mt-5"><div class="card shadow mx-auto" style="max-width: 500px;"><div class="card-header bg-success text-white"><h4>{{ 'Create' if uid == 'new' else 'Modify' }} User</h4></div><div class="card-body"><form method="POST"><div class="mb-3"><label>Name</label><input type="text" name="name" class="form-control" value="{{ user.name if user else '' }}" required></div><div class="mb-3"><label>Username</label><input type="text" name="username" class="form-control" value="{{ user.username if user else '' }}" required></div><div class="mb-3"><label>Password</label>{% if uid == 'new' %}<input type="text" name="password" class="form-control" required placeholder="Set initial password">{% elif session['role'] == 'SuperAdmin' %}<input type="text" name="password" class="form-control" placeholder="Enter new to change" value="{{ user.password }}">{% else %}<input type="text" class="form-control" value="******" disabled><small class="text-muted d-block mt-1"><i class="bi bi-lock-fill"></i> Only SuperAdmin can change other users' passwords.<br>Users can change their own password from the login screen.</small>{% endif %}</div><div class="mb-3"><label>Role</label><select name="role" class="form-select"><option value="Viewer" {% if user and user.role == 'Viewer' %}selected{% endif %}>Viewer (View Assigned & Receive)</option><option value="Editor" {% if user and user.role == 'Editor' %}selected{% endif %}>Editor (Data Entry)</option><option value="Admin" {% if user and user.role == 'Admin' %}selected{% endif %}>Admin (Standard)</option>{% if session['role'] == 'SuperAdmin' %}<option value="SuperAdmin" {% if user and user.role == 'SuperAdmin' %}selected{% endif %}>SuperAdmin (Full Access)</option>{% endif %}</select></div><button type="submit" class="btn btn-success w-100">Save</button></form></div></div></div></body></html>"""


# ==========================================
# 4. ROUTES
# ==========================================


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('change_password'): return redirect(url_for('change_password'))
        users = db.collection('users').where('username', '==', request.form['username']).where('password', '==', request.form['password']).stream()
        user = next(users, None)
        if user:
            ud = user.to_dict()
            # MARK SESSION PERMANENT FOR TIMEOUT
            session.permanent = True
            session.update({'user_id': user.id, 'user_name': ud['name'], 'role': ud['role']})
            db.collection('login_logs').add({'username': ud['username'], 'name': ud['name'], 'role': ud['role'], 'timestamp': datetime.utcnow()})
            return redirect(url_for('dashboard'))
        flash('Invalid Login')
    return render_template_string(HTML_LOGIN)

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        username = request.form['username']
        old_pass = request.form['old_password']
        new_pass = request.form['new_password']
        users = db.collection('users').where('username', '==', username).where('password', '==', old_pass).stream()
        user = next(users, None)
        if user:
            db.collection('users').document(user.id).update({'password': new_pass})
            flash('Password Updated Successfully! Please Login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid Username or Old Password.', 'danger')
    return render_template_string(HTML_CHANGE_PASS)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- UPDATED DASHBOARD ROUTE ---
@app.route('/')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', '').strip().lower()
    status_filter = request.args.get('status', 'All') # Pending vs All
    
    per_page = 40
    indents = []
    
    docs = db.collection('indents').stream() 
    for doc in docs:
        i = doc.to_dict()
        i['id'] = doc.id
        
        # Security Filter
        if session['role'] == 'Viewer' and i.get('assigned_to') != session['user_name']: continue
        
        # Search Logic
        if search_query and search_query not in str(i.get('item', '')).lower():
            continue
            
        # PENDING LIST FILTER
        if status_filter == 'Pending' and i.get('received_status') == 'Received':
            continue
        
        try: i['serial_no'] = int(i.get('serial_no', 0))
        except: i['serial_no'] = 0
        
        if 'department' not in i and 'requester' in i: i['department'] = i['requester']
        i.setdefault('created_by', 'Unknown')
        i.setdefault('created_at', '') 
        i.setdefault('indent_person', '')
        i.setdefault('remarks', '')
        
        indents.append(i)
        
    # Sort Descending
    indents.sort(key=lambda x: x['serial_no'], reverse=True)
    
    total_items = len(indents)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_indents = indents[start:end]
    has_next = end < total_items
    users = [d.to_dict() for d in db.collection('users').stream()]
    
    return render_template_string(
        HTML_DASHBOARD_INDENT, 
        indents=paginated_indents, 
        session=session, 
        system='indent', 
        today=datetime.today().strftime('%Y-%m-%d'), 
        page=page, 
        has_next=has_next, 
        users=users,
        current_status=status_filter
    )

@app.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session or session['role'] == 'Viewer': return redirect(url_for('dashboard'))
    submitted_data = [] 
    if request.method == 'POST':
        items = request.form.getlist('item[]')
        reasons = request.form.getlist('reason[]')
        remarks_list = request.form.getlist('remarks[]') 
        quantities = request.form.getlist('quantity[]')
        units = request.form.getlist('unit[]')
        custom_units = request.form.getlist('custom_unit[]')
        
        dept_select = request.form.get('department_select')
        custom_dept = request.form.get('custom_department')
        final_dept = dept_select
        if dept_select == 'Other' and custom_dept:
            final_dept = custom_dept.upper()
            add_if_new('departments', final_dept)

        indent_person = request.form.get('indent_person')
        if indent_person: add_if_new('indent_persons', indent_person)

        current_serial = get_next_serial_number('indents')
        batch = db.batch()
        existing_units = get_units_list()
        
        for i in range(len(items)):
            final_unit = units[i]
            if final_unit == 'Other' and custom_units[i]:
                final_unit = custom_units[i].upper()
                if final_unit not in existing_units:
                    db.collection('units').add({'name': final_unit})
                    existing_units.append(final_unit)
            
            doc_ref = db.collection('indents').document()
            data = {
                'serial_no': current_serial + i, 
                'indent_date': request.form['indent_date'], 
                'department': final_dept,
                'indent_person': indent_person, 
                'assigned_to': request.form['assigned_to'], 
                'item': items[i], 
                'reason': reasons[i],
                'remarks': remarks_list[i] if i < len(remarks_list) else "",
                'quantity': int(quantities[i]), 
                'unit': final_unit, 
                'approval_status': 'Pending', 
                'received_status': 'Pending', 
                'created_by': session['user_name'],
                'created_at': datetime.now()
            }
            batch.set(doc_ref, data)
            submitted_data.append(data) 
        batch.commit()
        flash("Indent Batch Created Successfully!", "success")
        
    users = [d.to_dict() for d in db.collection('users').stream()]
    return render_template_string(HTML_CREATE_MULTI, users=users, unit_list=get_units_list(), departments=get_departments_list(), persons=get_people_list(), today=datetime.today().strftime('%Y-%m-%d'), session=session, system='indent', submitted_data=submitted_data)

@app.route('/edit/<i_id>', methods=['GET', 'POST'])
def edit_indent(i_id):
    if 'user_id' not in session or session['role'] == 'Viewer': return redirect(url_for('dashboard'))
    doc_ref = db.collection('indents').document(i_id)
    if request.method == 'POST':
        dept = request.form.get('department')
        add_if_new('departments', dept)
        person = request.form.get('indent_person')
        add_if_new('indent_persons', person)

        update_data = {
            'indent_date': request.form['indent_date'], 'department': dept, 'indent_person': person,
            'item': request.form['item'], 'reason': request.form['reason'], 'remarks': request.form.get('remarks'),
            'quantity': int(request.form['quantity']), 'unit': request.form['unit'], 'assigned_to': request.form['assigned_to']
        }
        if session['role'] in ['Admin', 'SuperAdmin']:
             if 'approval_status' in request.form: 
                 new_status = request.form['approval_status']
                 update_data['approval_status'] = new_status
                 if new_status != 'Approved': update_data['approved_by_name'] = ""

             if 'received_status' in request.form:
                 update_data['received_status'] = request.form['received_status']
                 if request.form['received_status'] == 'Received':
                     update_data['received_date'] = request.form.get('received_date', datetime.today().strftime('%Y-%m-%d'))
                 else:
                     update_data['received_date'] = ""
        doc_ref.update(update_data)
        return redirect(url_for('dashboard'))
    
    users = [d.to_dict() for d in db.collection('users').stream()]
    data = doc_ref.get().to_dict()
    if 'department' not in data and 'requester' in data: data['department'] = data['requester']
    data.setdefault('indent_person', '')
    data.setdefault('remarks', '')
    return render_template_string(HTML_EDIT, users=users, unit_list=get_units_list(), departments=get_departments_list(), persons=get_people_list(), data=data, session=session, system='indent')

@app.route('/delete/<i_id>')
def delete_indent(i_id):
    if session['role'] not in ['Admin', 'SuperAdmin']: return redirect(url_for('dashboard'))
    if check_is_last_entry('indents', i_id): db.collection('indents').document(i_id).delete()
    else: flash('Error: Only last entry can be deleted.', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/bulk_update', methods=['POST'])
def bulk_update():
    if session['role'] not in ['Admin', 'SuperAdmin']: return redirect(url_for('dashboard'))
    ids = request.form.getlist('selected_ids[]')
    action = request.form.get('action')
    if not ids: return redirect(url_for('dashboard'))
    batch = db.batch()
    for i_id in ids:
        doc_ref = db.collection('indents').document(i_id)
        if action == 'Received':
            r_date = request.form.get('bulk_received_date')
            batch.update(doc_ref, {'received_status': 'Received', 'received_date': r_date})
        else:
            update_dict = {'approval_status': action}
            if action == 'Approved': update_dict['approved_by_name'] = request.form.get('approver_name')
            else: update_dict['approved_by_name'] = ""
            batch.update(doc_ref, update_dict)
    batch.commit()
    return redirect(url_for('dashboard'))


@app.route('/mark_received/<i_id>', methods=['POST'])
def mark_received(i_id):
    doc_ref = db.collection('indents').document(i_id)
    doc = doc_ref.get().to_dict()
    if session['role'] in ['Admin', 'SuperAdmin'] or (session['role'] == 'Viewer' and doc.get('assigned_to') == session['user_name']):
        r_date = request.form.get('received_date')
        if not r_date: r_date = datetime.today().strftime('%Y-%m-%d')
        doc_ref.update({'received_status': 'Received', 'received_date': r_date})
    return redirect(url_for('dashboard'))

@app.route('/reports', methods=['GET', 'POST'])
def reports():
    if 'user_id' not in session: return redirect(url_for('login'))
    filters = {'start_date': '', 'end_date': '', 'dept_filter': '', 'assigned_filter': 'All', 'status': 'All', 'received_status': 'All', 'sort_by': 'Date'}
    results = []
    users = [d.to_dict() for d in db.collection('users').stream()]
    if request.method == 'POST':
        filters.update({k: request.form.get(k) for k in filters})
        for doc in db.collection('indents').stream():
            d = doc.to_dict()
            d['id'] = doc.id
            try: d['serial_no'] = int(d.get('serial_no', 0))
            except: d['serial_no'] = 0
            if 'department' not in d and 'requester' in d: d['department'] = d['requester']
            d.setdefault('indent_person', '')
            d.setdefault('remarks', '')
            if filters['start_date'] and d['indent_date'] < filters['start_date']: continue
            if filters['end_date'] and d['indent_date'] > filters['end_date']: continue
            if filters['status'] != 'All' and d['approval_status'] != filters['status']: continue
            if filters['dept_filter'] and filters['dept_filter'].lower() not in d['department'].lower(): continue
            if filters['assigned_filter'] != 'All' and d.get('assigned_to') != filters['assigned_filter']: continue
            if filters['received_status'] == 'Received' and d.get('received_status') != 'Received': continue
            if filters['received_status'] == 'Pending' and d.get('received_status') == 'Received': continue
            results.append(d)
        if filters['sort_by'] == 'Department': results.sort(key=lambda x: x['department'])
        elif filters['sort_by'] == 'Assigned': results.sort(key=lambda x: x['assigned_to'])
        else: results.sort(key=lambda x: x['serial_no'], reverse=True)
        if request.form.get('action') == 'export':
            if not results: flash("No data", "warning")
            else:
                df = pd.DataFrame(results)[['serial_no', 'indent_date', 'department', 'indent_person', 'item', 'quantity', 'unit', 'approval_status', 'approved_by_name', 'received_status', 'assigned_to', 'reason', 'remarks']]
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
                output.seek(0)
                return send_file(output, download_name="Indent_Report.xlsx", as_attachment=True)
    return render_template_string(HTML_REPORTS, session=session, indents=results, filters=filters, users=users, current_time=datetime.now().strftime("%Y-%m-%d"), system='indent')

# --- PAYMENT ROUTES ---
@app.route('/payments')
def payment_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    payments = []
    for doc in db.collection('payments').stream():
        p = doc.to_dict()
        p['id'] = doc.id
        try: p['serial_no'] = int(p.get('serial_no', 0))
        except: p['serial_no'] = 0
        if p.get('status') == 'Done': continue
        payments.append(p)
    payments.sort(key=lambda x: x.get('serial_no', 0), reverse=True)
    return render_template_string(HTML_DASHBOARD_PAYMENT, payments=payments, session=session, system='payment')

@app.route('/payments/create', methods=['GET', 'POST'])
def create_payment():
    if session['role'] == 'Viewer': return redirect(url_for('payment_dashboard'))
    if request.method == 'POST':
        new_serial = get_next_serial_number('payments')
        entry_type = request.form.get('entry_type', 'Bill')
        
        data = {
            'serial_no': new_serial,
            'status': request.form.get('status', 'Pending'),
            'approved_by': request.form['approved_by'],
            'created_at': datetime.now(),
            'type': entry_type,
            'payment_date': '', 'payment_mode': '', 'transaction_ref': ''
        }
        
        if entry_type == 'Bill':
            data.update({
                'party_name': request.form['party_name'],
                'bill_number': request.form['bill_number'],
                'bill_date': request.form['bill_date'],
                'due_date': request.form['due_date'],
                'amount': request.form['amount']
            })
        else:
            bank_details = ""
            if request.form['payment_type'] == 'Advance':
                bank_details = f"{request.form['bank_name']}, Br:{request.form['branch_name']}, Acc:{request.form['account_no']}, IFSC:{request.form['ifsc']}"
            
            data.update({
                'party_name': request.form['adv_party_name'],
                'quotation_no': request.form['quotation_no'],
                'item_detail': request.form['item_detail'],
                'qty': request.form['qty'],
                'price': request.form['price'],
                'tax': request.form['tax'],
                'freight': request.form['freight'],
                'amount': request.form['adv_amount'],
                'payment_type': request.form['payment_type'],
                'delivery_time': request.form['delivery_time'],
                'bank_details': bank_details
            })

        db.collection('payments').add(data)
        return redirect(url_for('payment_dashboard'))
    return render_template_string(HTML_CREATE_PAYMENT, today=datetime.today().strftime('%Y-%m-%d'), session=session, system='payment')

@app.route('/payments/edit/<p_id>', methods=['GET', 'POST'])
def edit_payment(p_id):
    if session['role'] == 'Viewer': return redirect(url_for('payment_dashboard'))
    doc_ref = db.collection('payments').document(p_id)
    if request.method == 'POST':
        update_data = {
            'party_name': request.form['party_name'], 
            'amount': request.form['amount'], 
            'approved_by': request.form['approved_by'], 
            'status': request.form['status']
        }
        if 'bill_number' in request.form: update_data['bill_number'] = request.form['bill_number']
        if 'bill_date' in request.form: update_data['bill_date'] = request.form['bill_date']
        if 'due_date' in request.form: update_data['due_date'] = request.form['due_date']
        if 'quotation_no' in request.form: update_data['quotation_no'] = request.form['quotation_no']
        if 'item_detail' in request.form: update_data['item_detail'] = request.form['item_detail']
        if 'delivery_time' in request.form: update_data['delivery_time'] = request.form['delivery_time']
        
        if request.form['status'] == 'Done':
            update_data.update({'payment_date': request.form.get('payment_date'), 'payment_mode': request.form.get('payment_mode'), 'transaction_ref': request.form.get('transaction_ref')})
        doc_ref.update(update_data)
        return redirect(url_for('payment_dashboard'))
    return render_template_string(HTML_EDIT_PAYMENT, data=doc_ref.get().to_dict(), session=session, system='payment')

@app.route('/payments/delete/<p_id>')
def delete_payment(p_id):
    if session['role'] not in ['Admin', 'SuperAdmin']: return redirect(url_for('payment_dashboard'))
    if check_is_last_entry('payments', p_id): db.collection('payments').document(p_id).delete()
    else: flash('Error: Only last payment entry can be deleted.', 'danger')
    return redirect(url_for('payment_dashboard'))

@app.route('/payment_reports', methods=['GET', 'POST'])
def payment_reports():
    if 'user_id' not in session: return redirect(url_for('login'))
    filters = {'start_date': '', 'end_date': '', 'party_filter': '', 'status': 'All', 'sort_by': 'Party'}
    results = []
    if request.method == 'POST':
        filters.update({k: request.form.get(k) for k in filters})
        for doc in db.collection('payments').stream():
            p = doc.to_dict()
            p['id'] = doc.id
            try: p['serial_no'] = int(p.get('serial_no', 0))
            except: p['serial_no'] = 0
            
            check_date = p.get('bill_date') or p.get('created_at').strftime('%Y-%m-%d')
            if filters['start_date'] and check_date < filters['start_date']: continue
            if filters['end_date'] and check_date > filters['end_date']: continue
            if filters['status'] != 'All' and p['status'] != filters['status']: continue
            if filters['party_filter'] and filters['party_filter'].lower() not in p['party_name'].lower(): continue
            results.append(p)
        
        if filters['sort_by'] == 'Party': results.sort(key=lambda x: x.get('party_name', ''))
        else: results.sort(key=lambda x: x.get('serial_no', 0), reverse=True)
        
        if request.form.get('action') == 'export':
            if not results: flash("No data", "warning")
            else:
                bills, advances = [], []
                for r in results:
                    base = {'Serial': r['serial_no'], 'Party Name': r['party_name'], 'Amount': r['amount'], 'Status': r['status'], 'Approved By': r['approved_by'], 'Paid Date': r.get('payment_date', ''), 'Paid Mode': r.get('payment_mode', ''), 'Trans Ref': r.get('transaction_ref', '')}
                    if r.get('type') == 'Advance':
                        adv_row = base.copy()
                        adv_row.update({'Quotation No': r.get('quotation_no', ''), 'Item Detail': r.get('item_detail', ''), 'Qty': r.get('qty', ''), 'Price': r.get('price', ''), 'Tax': r.get('tax', ''), 'Freight': r.get('freight', ''), 'Payment Type': r.get('payment_type', ''), 'Delivery Time': r.get('delivery_time', ''), 'Bank Details': r.get('bank_details', '')})
                        advances.append(adv_row)
                    else:
                        bill_row = base.copy()
                        bill_row.update({'Bill Number': r.get('bill_number', ''), 'Bill Date': r.get('bill_date', ''), 'Due Date': r.get('due_date', '')})
                        bills.append(bill_row)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    pd.DataFrame(bills).to_excel(writer, sheet_name='Regular Bills', index=False) if bills else pd.DataFrame([{'Info': 'No Bills'}]).to_excel(writer, sheet_name='Regular Bills', index=False)
                    pd.DataFrame(advances).to_excel(writer, sheet_name='Advance Orders', index=False) if advances else pd.DataFrame([{'Info': 'No Advances'}]).to_excel(writer, sheet_name='Advance Orders', index=False)
                output.seek(0)
                return send_file(output, download_name="Payment_Report.xlsx", as_attachment=True)
                
    return render_template_string(HTML_REPORTS_PAYMENT, session=session, payments=results, filters=filters, current_time=datetime.now().strftime("%Y-%m-%d"), system='payment')

# --- SETTINGS & USERS ---
@app.route('/settings')
def settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('dashboard'))
    units = [dict(id=d.id, **d.to_dict()) for d in db.collection('units').stream()]
    users = [dict(id=d.id, **d.to_dict()) for d in db.collection('users').stream()]
    logs = [dict(id=d.id, **d.to_dict()) for d in db.collection('login_logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).stream()] if session.get('role') == 'SuperAdmin' else []
    return render_template_string(HTML_SETTINGS, session=session, units=units, users=users, logs=logs, system='indent')

@app.route('/settings/add_unit', methods=['POST'])
def add_unit():
    if session.get('role') in ['Admin', 'SuperAdmin']:
        unit_name = request.form['unit_name'].upper()
        if not list(db.collection('units').where('name', '==', unit_name).stream()): db.collection('units').add({'name': unit_name})
    return redirect(url_for('settings'))

@app.route('/settings/delete_unit/<uid>')
def delete_unit(uid):
    if session.get('role') in ['Admin', 'SuperAdmin']: db.collection('units').document(uid).delete()
    return redirect(url_for('settings'))

@app.route('/users/edit/<uid>', methods=['GET', 'POST'])
def edit_user(uid):
    if session['role'] not in ['Admin', 'SuperAdmin']: return redirect(url_for('dashboard'))
    user_data = None if uid == 'new' else db.collection('users').document(uid).get().to_dict()
    if request.method == 'POST':
        data = {'name': request.form['name'], 'username': request.form['username'], 'role': request.form['role']}
        pwd = request.form.get('password')
        if uid == 'new':
            data['password'] = pwd
            db.collection('users').add(data)
        else:
            if session['role'] == 'SuperAdmin' and pwd: data['password'] = pwd
            db.collection('users').document(uid).update(data)
        return redirect(url_for('settings'))
    return render_template_string(HTML_EDIT_USER, uid=uid, user=user_data, session=session, system='indent')

@app.route('/users/delete/<uid>')
def delete_user(uid):
    if session['role'] not in ['Admin', 'SuperAdmin']: return redirect(url_for('settings'))
    target_user_ref = db.collection('users').document(uid)
    target_user = target_user_ref.get().to_dict()
    if session['role'] == 'Admin' and target_user.get('role') == 'SuperAdmin':
        flash("Admins cannot delete SuperAdmins.", "danger")
    elif uid == session['user_id']:
        flash("You cannot delete yourself.", "warning")
    else:
        target_user_ref.delete()
    return redirect(url_for('settings'))
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
