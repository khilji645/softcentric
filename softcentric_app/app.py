from flask import Flask, render_template, request, redirect, url_for, session, flash
import json
import os
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ================= PATH FIX =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
EXPENSES_FILE = os.path.join(DATA_DIR, "expenses.json")
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")
MISC_FILE = os.path.join(DATA_DIR, "misc_expenses.json")

# Ensure JSON files exist
for file in [USERS_FILE, PROJECTS_FILE, EXPENSES_FILE, PROGRESS_FILE, MESSAGES_FILE, MISC_FILE]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump([], f)
# ==========================================================

# -------------------- Decorators --------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function

# -------------------- JSON Helpers --------------------
def read_json(file):
    with open(file, "r") as f:
        return json.load(f)

def write_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def get_unread_count(username):
    messages = read_json(MESSAGES_FILE)
    return sum(1 for m in messages if m["receiver"] == username and not m.get("read", False))

# -------------------- Context Processor --------------------
@app.context_processor
def inject_unread_count():
    username = session.get("username")
    unread_count = get_unread_count(username) if username else 0
    return dict(unread_count=unread_count)

# -------------------- Authentication --------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        users = read_json(USERS_FILE)
        for user in users:
            if user["username"] == username and user["password"] == password:
                session["username"] = username
                session["role"] = user["role"]
                return redirect(url_for("dashboard"))
        flash("Invalid username or password")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------- Dashboard --------------------
@app.route("/dashboard")
@login_required
def dashboard():
    role = session.get("role")
    username = session.get("username")

    all_projects = read_json(PROJECTS_FILE)
    expenses = read_json(EXPENSES_FILE)
    progress = read_json(PROGRESS_FILE)
    messages = read_json(MESSAGES_FILE)

    show_completed = request.args.get("completed", "").lower() == "true"

    if role != "admin":
        projects = [p for p in all_projects if username in p["users"]]
        project_ids = [p["id"] for p in projects]
        expenses = [e for e in expenses if e["project_id"] in project_ids]
        progress = [p for p in progress if p["project_id"] in project_ids]
    else:
        projects = all_projects

    filtered_projects = [p for p in projects if (p.get("status", "").lower() == "completed") == show_completed]
    unread_count = get_unread_count(username)

    return render_template(
        "dashboard.html",
        role=role,
        projects=filtered_projects,
        expenses=expenses,
        progress=progress,
        unread_count=unread_count,
        show_completed=show_completed
    )

# -------------------- Project Routes --------------------
@app.route("/project/add", methods=["GET", "POST"])
@login_required
@admin_required
def project_add():
    users = read_json(USERS_FILE)
    if request.method == "POST":
        projects = read_json(PROJECTS_FILE)
        new_project = {
            "id": len(projects) + 1,
            "name": request.form["name"],
            "description": request.form["description"],
            "users": request.form.getlist("users"),
            "status": "in-progress"
        }
        projects.append(new_project)
        write_json(PROJECTS_FILE, projects)
        return redirect(url_for("dashboard"))
    return render_template("project_add.html", users=users)

@app.route("/project/edit/<int:project_id>", methods=["GET", "POST"])
@login_required
@admin_required
def project_edit(project_id):
    projects = read_json(PROJECTS_FILE)
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        flash("Project not found")
        return redirect(url_for("dashboard"))
    users = read_json(USERS_FILE)
    if request.method == "POST":
        project["name"] = request.form["name"]
        project["description"] = request.form["description"]
        project["users"] = request.form.getlist("users")
        write_json(PROJECTS_FILE, projects)
        return redirect(url_for("dashboard"))
    return render_template("project_add.html", project=project, users=users)

@app.route("/project/delete/<int:project_id>")
@login_required
@admin_required
def project_delete(project_id):
    projects = read_json(PROJECTS_FILE)
    projects = [p for p in projects if p["id"] != project_id]
    write_json(PROJECTS_FILE, projects)
    return redirect(url_for("dashboard"))

@app.route("/project/complete/<int:project_id>")
@login_required
@admin_required
def project_complete(project_id):
    projects = read_json(PROJECTS_FILE)
    project = next((p for p in projects if p["id"] == project_id), None)
    if project:
        project["status"] = "completed"
        write_json(PROJECTS_FILE, projects)
        flash(f'Project "{project["name"]}" marked as completed.')
    return redirect(url_for("dashboard"))

@app.route("/project/<int:project_id>")
@login_required
def project_detail(project_id):
    projects = read_json(PROJECTS_FILE)
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        flash("Project not found")
        return redirect(url_for("dashboard"))
    if session.get("role") != "admin" and session.get("username") not in project["users"]:
        flash("Access denied")
        return redirect(url_for("dashboard"))
    expenses = [e for e in read_json(EXPENSES_FILE) if e["project_id"] == project_id]
    progress = [p for p in read_json(PROGRESS_FILE) if p["project_id"] == project_id]
    for p in progress:
        if "instructions" not in p:
            p["instructions"] = ""
    return render_template("project_detail.html", project=project, expenses=expenses, progress=progress, role=session.get("role"))

# -------------------- Expense Routes --------------------
@app.route("/expense/add", methods=["GET", "POST"])
@login_required
def add_expense():
    projects = read_json(PROJECTS_FILE)
    if session.get("role") != "admin":
        projects = [p for p in projects if session["username"] in p["users"]]
    if request.method == "POST":
        expenses = read_json(EXPENSES_FILE)
        new_expense = {
            "id": len(expenses) + 1,
            "project_id": int(request.form["project_id"]),
            "amount": float(request.form["amount"]),
            "description": request.form["description"],
            "date": request.form["date"]
        }
        expenses.append(new_expense)
        write_json(EXPENSES_FILE, expenses)
        return redirect(url_for("dashboard"))
    return render_template("add_expense.html", projects=projects)

@app.route("/expense/view")
@login_required
def view_expense():
    role = session.get("role")
    expenses = read_json(EXPENSES_FILE)
    all_projects = read_json(PROJECTS_FILE)
    if role != "admin":
        user_projects = [p["id"] for p in all_projects if session["username"] in p["users"]]
        expenses = [e for e in expenses if e["project_id"] in user_projects]
    project_filter = request.args.get("project", "").strip()
    desc_filter = request.args.get("description", "").strip()
    if project_filter:
        expenses = [e for e in expenses if str(e["project_id"]) == project_filter]
    if desc_filter:
        expenses = [e for e in expenses if e.get("description", "").lower() == desc_filter.lower()]
    projects = {p["id"]: p["name"] for p in all_projects}
    project_options = sorted(all_projects, key=lambda x: x["name"])
    description_options = sorted({e.get("description", "") for e in expenses if e.get("description")})
    return render_template(
        "view_expense.html",
        expenses=expenses,
        projects=projects,
        project_filter=project_filter,
        desc_filter=desc_filter,
        project_options=project_options,
        description_options=description_options,
        role=role
    )

# -------------------- Progress Routes --------------------
@app.route("/progress/add", methods=["GET", "POST"])
@login_required
def add_progress():
    projects = read_json(PROJECTS_FILE)
    username = session.get("username")
    if session.get("role") != "admin":
        projects = [p for p in projects if username in p["users"]]
    if request.method == "POST":
        progress = read_json(PROGRESS_FILE)
        new_progress = {
            "id": len(progress) + 1,
            "project_id": int(request.form["project_id"]),
            "update": request.form["update"],
            "date": request.form["date"],
            "user": username
        }
        progress.append(new_progress)
        write_json(PROGRESS_FILE, progress)
        return redirect(url_for("dashboard"))
    return render_template("add_progress.html", projects=projects)

@app.route("/progress/view")
@login_required
def view_progress():
    role = session.get("role")
    progress = read_json(PROGRESS_FILE)
    all_projects = read_json(PROJECTS_FILE)
    if role != "admin":
        user_project_ids = [p["id"] for p in all_projects if session["username"] in p["users"]]
        all_projects = [p for p in all_projects if p["id"] in user_project_ids]
        progress = [p for p in progress if p["project_id"] in user_project_ids]
    project_filter = request.args.get("project", "")
    user_filter = request.args.get("user", "")
    show_completed = request.args.get("completed", "false").lower() == "true"
    projects_in_progress = {p["id"]: p for p in all_projects if p.get("status") != "completed"}
    projects_completed = {p["id"]: p for p in all_projects if p.get("status") == "completed"}
    if project_filter:
        project_ids = [int(project_filter)]
        progress = [p for p in progress if p["project_id"] in project_ids]
    if user_filter:
        progress = [p for p in progress if user_filter.lower() in p.get("user", "").lower()]
    project_options = sorted(all_projects, key=lambda x: x["name"])
    user_options = sorted({p.get("user", "Unknown") for p in progress if p.get("user")})
    projects = projects_completed if show_completed else projects_in_progress
    return render_template(
        "view_progress.html",
        progress=progress,
        projects=projects,
        role=role,
        project_filter=project_filter,
        user_filter=user_filter,
        project_options=project_options,
        user_options=user_options,
        show_completed=show_completed
    )

@app.route("/progress/<int:progress_id>/instruction", methods=["POST"])
@login_required
@admin_required
def add_instruction(progress_id):
    instruction_text = request.form.get("instruction")
    if not instruction_text:
        flash("Instruction cannot be empty")
        return redirect(request.referrer)
    progress = read_json(PROGRESS_FILE)
    updated = False
    for p in progress:
        if p["id"] == progress_id:
            p["instructions"] = instruction_text
            updated = True
            break
    if updated:
        write_json(PROGRESS_FILE, progress)
        flash("Instruction added successfully")
    else:
        flash("Progress entry not found")
    return redirect(request.referrer)

# -------------------- User Management Routes --------------------
@app.route("/users/manage", methods=["GET", "POST"])
@login_required
@admin_required
def manage_users():
    users = read_json(USERS_FILE)
    if request.method == "POST":
        new_user = {
            "username": request.form["username"],
            "password": request.form["password"],
            "role": request.form["role"]
        }
        users.append(new_user)
        write_json(USERS_FILE, users)
        return redirect(url_for("manage_users"))
    return render_template("manage_users.html", users=users)

@app.route("/user/<username>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(username):
    users = read_json(USERS_FILE)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        flash("User not found")
        return redirect(url_for("manage_users"))
    if request.method == "POST":
        new_username = request.form.get("username")
        new_role = request.form.get("role")
        if new_username and new_role:
            user["username"] = new_username
            user["role"] = new_role
            write_json(USERS_FILE, users)
            flash("User updated successfully")
            return redirect(url_for("manage_users"))
        else:
            flash("All fields are required")
    return render_template("edit_user.html", user=user)

@app.route("/user/<username>/delete")
@login_required
@admin_required
def delete_user(username):
    users = read_json(USERS_FILE)
    users = [u for u in users if u["username"] != username]
    write_json(USERS_FILE, users)
    flash("User deleted successfully")
    return redirect(url_for("manage_users"))

@app.route("/users/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    users = read_json(USERS_FILE)
    if request.method == "POST":
        old_password = request.form.get("old_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        for user in users:
            if user["username"] == session["username"]:
                if user["password"] != old_password:
                    flash("Old password is incorrect")
                    return redirect(url_for("change_password"))
                if new_password != confirm_password:
                    flash("New passwords do not match")
                    return redirect(url_for("change_password"))
                user["password"] = new_password
                write_json(USERS_FILE, users)
                flash("Password changed successfully")
                return redirect(url_for("dashboard"))
    return render_template("change_password.html")

# -------------------- Messaging Routes --------------------
@app.route("/messages")
@login_required
def messages():
    current_user = session["username"]
    all_users = read_json(USERS_FILE)
    messages_data = read_json(MESSAGES_FILE)
    conversations = {}
    unread_counts = {}
    for msg in messages_data:
        if current_user in [msg["sender"], msg["receiver"]]:
            other_user = msg["receiver"] if msg["sender"] == current_user else msg["sender"]
            if other_user not in conversations:
                conversations[other_user] = []
                unread_counts[other_user] = 0
            conversations[other_user].append(msg)
            if msg["receiver"] == current_user and not msg.get("read", False):
                unread_counts[other_user] += 1
    for conv in conversations.values():
        conv.sort(key=lambda x: x.get("timestamp", ""))
    return render_template("messages.html", conversations=conversations, current_user=current_user, all_users=all_users, unread_counts=unread_counts)

@app.route("/messages/<receiver>", methods=["GET", "POST"])
@login_required
def chat_with(receiver):
    username = session["username"]
    messages_data = read_json(MESSAGES_FILE)
    conversation = [m for m in messages_data if (m["sender"] == username and m["receiver"] == receiver) or (m["sender"] == receiver and m["receiver"] == username)]
    for m in conversation:
        if "timestamp" not in m:
            m["timestamp"] = "1970-01-01T00:00:00"
    conversation.sort(key=lambda x: x["timestamp"])
    updated = False
    for m in messages_data:
        if m["receiver"] == username and m["sender"] == receiver and not m.get("read", False):
            m["read"] = True
            updated = True
    if updated:
        write_json(MESSAGES_FILE, messages_data)
    if request.method == "POST":
        content = request.form.get("message")
        if content:
            new_message = {
                "id": len(messages_data) + 1,
                "sender": username,
                "receiver": receiver,
                "message": content,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "read": False
            }
            messages_data.append(new_message)
            write_json(MESSAGES_FILE, messages_data)
            return redirect(url_for("chat_with", receiver=receiver))
    return render_template("chat.html", conversation=conversation, receiver=receiver, username=username)

@app.route("/messages/send", methods=["POST"])
@login_required
def send_message():
    sender = session["username"]
    receiver = request.form.get("receiver")
    message_text = request.form.get("message")
    if not receiver or not message_text:
        flash("Both receiver and message are required")
        return redirect(url_for("messages"))
    messages_data = read_json(MESSAGES_FILE)
    new_message = {
        "id": len(messages_data) + 1,
        "sender": sender,
        "receiver": receiver,
        "message": message_text,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read": False
    }
    messages_data.append(new_message)
    write_json(MESSAGES_FILE, messages_data)
    return redirect(url_for("messages"))

@app.route("/messages/unread_details")
@login_required
def unread_details():
    username = session["username"]
    messages_data = read_json(MESSAGES_FILE)
    unread = [m for m in messages_data if m["receiver"] == username and not m.get("read", False)]
    return {"unread": unread}

# -------------------- Miscellaneous Expense Routes --------------------
@app.route("/misc/add", methods=["GET", "POST"])
@login_required
def add_misc_expense():
    role = session.get("role")
    users = read_json(USERS_FILE)
    if request.method == "POST":
        misc_expenses = read_json(MISC_FILE)
        new_expense = {
            "id": len(misc_expenses) + 1,
            "date": request.form["date"],
            "user": request.form["user"],
            "description": request.form["description"],
            "amount": float(request.form["amount"]),
            "paid_by": request.form["paid_by"],
            "remarks": request.form.get("remarks", "")
        }
        misc_expenses.append(new_expense)
        write_json(MISC_FILE, misc_expenses)
        flash("Miscellaneous expense added successfully")
        return redirect(url_for("view_misc_expense"))
    return render_template("add_misc_expense.html", users=users, role=role)

@app.route("/misc/view")
@login_required
def view_misc_expense():
    role = session.get("role")
    misc_expenses = read_json(MISC_FILE)
    user_filter = request.args.get("user", "").strip()
    desc_filter = request.args.get("description", "").strip()
    paid_by_filter = request.args.get("paid_by", "").strip()
    month_filter = request.args.get("month", "").strip()
    show_previous = request.args.get("previous", "false").lower() == "true"
    if role != "admin":
        misc_expenses = [e for e in misc_expenses if e["user"] == session["username"]]
    current_month = datetime.now().strftime("%Y-%m")
    if show_previous:
        misc_expenses = [e for e in misc_expenses if e["date"][:7] < current_month]
    else:
        misc_expenses = [e for e in misc_expenses if e["date"][:7] == current_month]
    if user_filter and role == "admin":
        misc_expenses = [e for e in misc_expenses if e["user"] == user_filter]
    if desc_filter:
        misc_expenses = [e for e in misc_expenses if e["description"] == desc_filter]
    if paid_by_filter:
        misc_expenses = [e for e in misc_expenses if e.get("paid_by", "") == paid_by_filter]
    if month_filter:
        misc_expenses = [e for e in misc_expenses if e["date"][:7] == month_filter]
    all_expenses = read_json(MISC_FILE)
    users = sorted({e["user"] for e in all_expenses})
    descriptions = sorted({e["description"] for e in all_expenses})
    paid_by_list = sorted({e.get("paid_by", "") for e in all_expenses if e.get("paid_by")})
    months = sorted({e["date"][:7] for e in all_expenses}, reverse=True)
    total_amount = sum(float(e["amount"]) for e in misc_expenses)
    return render_template(
        "view_misc_expense.html",
        misc_expenses=misc_expenses,
        role=role,
        user_filter=user_filter,
        desc_filter=desc_filter,
        paid_by_filter=paid_by_filter,
        month_filter=month_filter,
        users=users,
        descriptions=descriptions,
        paid_by_list=paid_by_list,
        months=months,
        total_amount=total_amount,
        show_previous=show_previous
    )

# -------------------- Run App --------------------
if __name__ == "__main__":
    app.run(debug=True)
