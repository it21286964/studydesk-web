import os
from datetime import datetime, date
from pathlib import Path
from uuid import uuid4

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, abort
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from models import db, User, Module, Assignment, ExamEvent, StudyTopic, StudyPlan, StudyPlanItem, StudyGroup, StudyGroupMember, Resource, JointSession, Notification
from utils import (
    cycle_status, calculate_topic_priority, estimate_difficulty_from_text,
    create_exam_anchor, generate_study_plan_for_exam, reschedule_missed_items,
    create_or_join_group_for_exam, notify, allowed_file, assignments_due_for_reminder,
    clean_text, is_valid_email, is_strong_password, is_valid_module_code, bound_int,
    parse_dt_local, parse_date, extract_uploaded_text
)

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

scheduler = BackgroundScheduler(daemon=True)
_scheduler_started = False
APP_NAME = "StudyDesk"
ALLOWED_TASK_TYPES = {"assignment", "lab", "quiz", "exam", "project"}

#Tharusha
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def init_upload_folder():
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

init_upload_folder()

def seed_notifications():
    for assignment, label in assignments_due_for_reminder():
        if assignment.module and assignment.module.user_id:
            notify(
                assignment.module.user_id,
                "assignment",
                assignment.id,
                f"Reminder: {assignment.title} is due in {label}"
            )

def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    scheduler.add_job(seed_notifications, "interval", minutes=30, id="deadline_reminders", replace_existing=True)
    scheduler.start()
    _scheduler_started = True

@app.template_filter("dt")
def dt_filter(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value

def require_ownership(module_id: int):
    module = Module.query.get_or_404(module_id)
    if module.user_id != current_user.id:
        abort(403)
    return module

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = clean_text(request.form.get("name"))
        email = clean_text(request.form.get("email")).lower()
        password = request.form.get("password", "")
        program = clean_text(request.form.get("program"))
        location_pref = clean_text(request.form.get("location_pref"))
        availability = clean_text(request.form.get("availability"))
        study_goal = clean_text(request.form.get("study_goal"))

        if len(name) < 2 or len(name) > 80:
            flash("Name must be between 2 and 80 characters.")
            return redirect(url_for("register"))
        if not is_valid_email(email):
            flash("Enter a valid email address.")
            return redirect(url_for("register"))
        ok, message = is_strong_password(password)
        if not ok:
            flash(message)
            return redirect(url_for("register"))
        if User.query.filter_by(email=email).first():
            flash("Email already exists.")
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            program=program[:120],
            location_pref=location_pref[:120],
            availability=availability[:255],
            study_goal=study_goal[:255],
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("dashboard"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = clean_text(request.form.get("email")).lower()
        password = request.form.get("password", "")
        if not is_valid_email(email):
            flash("Enter a valid email address.")
            return redirect(url_for("login"))
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = clean_text(request.form.get("name"))
        email = clean_text(request.form.get("email")).lower()
        program = clean_text(request.form.get("program"))
        location_pref = clean_text(request.form.get("location_pref"))
        availability = clean_text(request.form.get("availability"))
        study_goal = clean_text(request.form.get("study_goal"))

        if len(name) < 2 or len(name) > 80:
            flash("Name must be between 2 and 80 characters.")
            return redirect(url_for("profile"))
        if not is_valid_email(email):
            flash("Enter a valid email address.")
            return redirect(url_for("profile"))

        duplicate = User.query.filter(User.email == email, User.id != current_user.id).first()
        if duplicate:
            flash("That email is already in use.")
            return redirect(url_for("profile"))

        current_user.name = name
        current_user.email = email
        current_user.program = program[:120]
        current_user.location_pref = location_pref[:120]
        current_user.availability = availability[:255]
        current_user.study_goal = study_goal[:255]
        db.session.commit()
        flash("Profile updated.")
        return redirect(url_for("profile"))

    return render_template("profile.html")


@app.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_password:
        flash("Current password is required.")
        return redirect(url_for("profile"))
    if not check_password_hash(current_user.password_hash, current_password):
        flash("Current password is incorrect.")
        return redirect(url_for("profile"))
    ok, message = is_strong_password(new_password)
    if not ok:
        flash(message)
        return redirect(url_for("profile"))
    if new_password != confirm_password:
        flash("Password confirmation does not match.")
        return redirect(url_for("profile"))
    if new_password == current_password:
        flash("New password must be different from the current password.")
        return redirect(url_for("profile"))

    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash("Password changed.")
    return redirect(url_for("profile"))

@app.route("/dashboard")
@login_required
def dashboard():
    modules = Module.query.filter_by(user_id=current_user.id).all()
    assignments = (
        Assignment.query.join(Module, Assignment.module_id == Module.id)
        .filter(Module.user_id == current_user.id)
        .all()
    )
    assignments = sorted(assignments, key=lambda a: (a.deadline, -a.priority_level, -a.credit_weight))
    exams = (
        ExamEvent.query.join(Module, ExamEvent.module_id == Module.id)
        .filter(Module.user_id == current_user.id)
        .order_by(ExamEvent.exam_date.asc())
        .all()
    )
    plans = StudyPlan.query.filter_by(user_id=current_user.id).all()
    groups = StudyGroupMember.query.filter_by(user_id=current_user.id).all()
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(10).all()
    stats = {
        "modules": len(modules),
        "assignments": len(assignments),
        "active_tasks": sum(1 for a in assignments if a.status != "Completed"),
        "exams": len(exams),
        "plans": len(plans),
        "groups": len(groups),
        "unread": Notification.query.filter_by(user_id=current_user.id, is_read=False).count(),
    }
    return render_template(
        "dashboard.html",
        modules=modules,
        assignments=assignments,
        exams=exams,
        plans=plans,
        groups=groups,
        notifications=notifications,
        stats=stats,
    )

@app.route("/modules", methods=["GET", "POST"])
@login_required
def modules():
    if request.method == "POST":
        code = clean_text(request.form.get("code")).upper()
        name = clean_text(request.form.get("name"))
        try:
            credits = bound_int(request.form.get("credits", 0), "Credits", 0, 60)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("modules"))

        if not is_valid_module_code(code):
            flash("Module code must be 2–20 characters and may include letters, numbers, spaces, or hyphens.")
            return redirect(url_for("modules"))
        if len(name) < 2 or len(name) > 120:
            flash("Module name must be between 2 and 120 characters.")
            return redirect(url_for("modules"))
        if Module.query.filter_by(user_id=current_user.id, code=code).first():
            flash("That module code already exists in your workspace.")
            return redirect(url_for("modules"))

        module = Module(user_id=current_user.id, code=code, name=name, credits=credits)
        db.session.add(module)
        db.session.commit()
        flash("Module added.")
        return redirect(url_for("modules"))
    items = Module.query.filter_by(user_id=current_user.id).all()
    return render_template("modules.html", modules=items)

@app.route("/modules/<int:module_id>/delete", methods=["POST"])
@login_required
def delete_module(module_id):
    module = require_ownership(module_id)
    db.session.delete(module)
    db.session.commit()
    flash("Module deleted.")
    return redirect(url_for("modules"))

@app.route("/assignments", methods=["GET", "POST"])
@login_required
def assignments():
    modules_list = Module.query.filter_by(user_id=current_user.id).all()
    if request.method == "POST":
        if not modules_list:
            flash("Add a module first.")
            return redirect(url_for("assignments"))
        try:
            module_id = int(request.form.get("module_id", 0))
            module = require_ownership(module_id)
        except (TypeError, ValueError):
            flash("Choose a valid module.")
            return redirect(url_for("assignments"))

        title = clean_text(request.form.get("title"))
        typ = request.form.get("type", "")
        deadline_raw = request.form.get("deadline", "")
        if not title or len(title) < 3 or len(title) > 200:
            flash("Task title must be between 3 and 200 characters.")
            return redirect(url_for("assignments"))
        if typ not in ALLOWED_TASK_TYPES:
            flash("Choose a valid task type.")
            return redirect(url_for("assignments"))
        try:
            deadline = parse_dt_local(deadline_raw, "Deadline")
            credit_weight = bound_int(request.form.get("credit_weight", 0), "Credit weight", 0, 100)
            priority_level = bound_int(request.form.get("priority_level", 1), "Priority level", 1, 10)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("assignments"))

        assignment = Assignment(
            module_id=module.id,
            title=title,
            type=typ,
            deadline=deadline,
            credit_weight=credit_weight,
            priority_level=priority_level,
        )
        db.session.add(assignment)
        db.session.commit()

        if typ == "exam":
            create_exam_anchor(module, deadline, assignment.id)
            create_or_join_group_for_exam(module, deadline, current_user)

        flash("Assignment saved.")
        return redirect(url_for("assignments"))

    items = (
        Assignment.query.join(Module, Assignment.module_id == Module.id)
        .filter(Module.user_id == current_user.id)
        .order_by(Assignment.deadline.asc())
        .all()
    )
    return render_template("assignments.html", assignments=items, modules=modules_list)

@app.route("/assignments/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.module.user_id != current_user.id:
        abort(403)
    db.session.delete(assignment)
    db.session.commit()
    flash("Assignment deleted.")
    return redirect(url_for("assignments"))

@app.route("/api/assignment/<int:assignment_id>/cycle", methods=["POST"])
@login_required
def assignment_cycle(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.module.user_id != current_user.id:
        abort(403)
    assignment.status = cycle_status(assignment.status)
    db.session.commit()
    return jsonify({"status": assignment.status})

@app.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_notification(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != current_user.id:
        abort(403)
    notif.is_read = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})
