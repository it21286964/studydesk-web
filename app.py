import os
import re
from datetime import datetime, date, time, timedelta
from pathlib import Path
from uuid import uuid4

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, abort
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from models import (
    db, User, Module, Assignment, ExamEvent, StudyTopic, StudyPlan, StudyPlanItem,
    StudyGroup, StudyGroupMember, Resource, JointSession, Notification
)
from utils import (
    cycle_status, status_class, calculate_topic_priority, estimate_difficulty_from_text,
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
ALLOWED_EXAM_KINDS = {"mid", "final", "other"}


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def init_folders():
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.static_folder, "images").mkdir(parents=True, exist_ok=True)
    Path(app.static_folder, "profile_pics").mkdir(parents=True, exist_ok=True)


init_folders()


@app.context_processor
def inject_globals():
    return {
        "app_name": APP_NAME,
        "now_year": datetime.now().year,
        "status_class": status_class,
    }


def require_ownership(module_id: int):
    module = Module.query.get_or_404(module_id)
    if module.user_id != current_user.id:
        abort(403)
    return module


def save_upload(uploaded, subfolder=""):
    filename = f"{uuid4().hex}_{secure_filename(uploaded.filename)}"
    if subfolder:
        target_dir = Path(app.static_folder) / subfolder
    else:
        target_dir = Path(app.config["UPLOAD_FOLDER"])
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    uploaded.save(path)
    return filename, path


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
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return value


@app.template_filter("status_css")
def status_css(value):
    return status_class(value)


def bucket_assignments(assignments):
    buckets = {"Overdue": [], "Due Today": [], "Due This Week": [], "Upcoming": []}
    today = date.today()
    end_of_week = today + timedelta(days=7)
    for item in assignments:
        due = item.deadline.date() if isinstance(item.deadline, datetime) else item.deadline
        if due < today:
            buckets["Overdue"].append(item)
        elif due == today:
            buckets["Due Today"].append(item)
        elif due <= end_of_week:
            buckets["Due This Week"].append(item)
        else:
            buckets["Upcoming"].append(item)
    return buckets


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

        uploaded = request.files.get("profile_picture")
        if uploaded and uploaded.filename:
            if not allowed_file(uploaded.filename):
                flash("Unsupported profile picture type.")
                return redirect(url_for("profile"))
            filename, _ = save_upload(uploaded, "profile_pics")
            current_user.profile_picture = f"profile_pics/{filename}"

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
        .order_by(Assignment.deadline.asc(), Assignment.priority_level.desc())
        .all()
    )
    exams = (
        ExamEvent.query.join(Module, ExamEvent.module_id == Module.id)
        .filter(Module.user_id == current_user.id)
        .order_by(ExamEvent.exam_start_date.asc())
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
        assignment_buckets=bucket_assignments(assignments),
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

        db.session.add(Module(user_id=current_user.id, code=code, name=name, credits=credits))
        db.session.commit()
        flash("Module added.")
        return redirect(url_for("modules"))
    items = Module.query.filter_by(user_id=current_user.id).all()
    return render_template("modules.html", modules=items)


@app.route("/modules/<int:module_id>/edit", methods=["GET", "POST"])
@login_required
def edit_module(module_id):
    module = require_ownership(module_id)
    if request.method == "POST":
        code = clean_text(request.form.get("code")).upper()
        name = clean_text(request.form.get("name"))
        try:
            credits = bound_int(request.form.get("credits", module.credits), "Credits", 0, 60)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("edit_module", module_id=module.id))
        if not is_valid_module_code(code):
            flash("Module code must be 2–20 characters and may include letters, numbers, spaces, or hyphens.")
            return redirect(url_for("edit_module", module_id=module.id))
        if len(name) < 2 or len(name) > 120:
            flash("Module name must be between 2 and 120 characters.")
            return redirect(url_for("edit_module", module_id=module.id))
        duplicate = Module.query.filter(Module.user_id == current_user.id, Module.code == code, Module.id != module.id).first()
        if duplicate:
            flash("That module code already exists in your workspace.")
            return redirect(url_for("edit_module", module_id=module.id))
        module.code = code
        module.name = name
        module.credits = credits
        db.session.commit()
        flash("Module updated.")
        return redirect(url_for("modules"))
    return render_template("module_edit.html", module=module)


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
        exam_kind = clean_text(request.form.get("exam_kind", "mid")).lower() or "mid"

        if not title or len(title) < 3 or len(title) > 200:
            flash("Task title must be between 3 and 200 characters.")
            return redirect(url_for("assignments"))
        if typ not in ALLOWED_TASK_TYPES:
            flash("Choose a valid task type.")
            return redirect(url_for("assignments"))

        try:
            credit_weight = bound_int(request.form.get("credit_weight", 0), "Credit weight", 0, 100)
            priority_level = bound_int(request.form.get("priority_level", 1), "Priority level", 1, 10)
            if typ != "exam":
                deadline = parse_dt_local(deadline_raw, "Deadline")
            else:
                deadline = None
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("assignments"))

        exam_start_date = exam_end_date = None
        if typ == "exam":
            if exam_kind not in ALLOWED_EXAM_KINDS:
                flash("Choose a valid exam type.")
                return redirect(url_for("assignments"))
            try:
                exam_start_date = parse_date(request.form.get("exam_start_date", ""), "Exam start date")
                exam_end_date = parse_date(request.form.get("exam_end_date", ""), "Exam end date")
            except ValueError as exc:
                flash(str(exc))
                return redirect(url_for("assignments"))
            if exam_end_date < exam_start_date:
                flash("Exam end date cannot be before the start date.")
                return redirect(url_for("assignments"))
            deadline = datetime.combine(exam_end_date, time(23, 59))

        assignment = Assignment(
            module_id=module.id,
            title=title,
            type=typ,
            deadline=deadline,
            credit_weight=credit_weight,
            priority_level=priority_level,
            exam_kind=exam_kind if typ == "exam" else "",
            exam_start_date=exam_start_date,
            exam_end_date=exam_end_date,
        )
        db.session.add(assignment)
        db.session.commit()

        if typ == "exam" and exam_kind in {"mid", "final"}:
            create_exam_anchor(module, exam_start_date, exam_end_date, assignment.id, exam_kind)
            create_or_join_group_for_exam(module, exam_start_date, exam_end_date, current_user)

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
    return jsonify({"status": assignment.status, "class": status_class(assignment.status)})


@app.route("/planner", methods=["GET", "POST"])
@login_required
def planner():
    modules_list = Module.query.filter_by(user_id=current_user.id).all()
    if request.method == "POST":
        if not modules_list:
            flash("Add a module first.")
            return redirect(url_for("planner"))
        try:
            module_id = int(request.form.get("module_id", 0))
            module = require_ownership(module_id)
        except (TypeError, ValueError):
            flash("Choose a valid module.")
            return redirect(url_for("planner"))

        title = clean_text(request.form.get("title"))
        if len(title) < 2 or len(title) > 200:
            flash("Topic title must be between 2 and 200 characters.")
            return redirect(url_for("planner"))

        try:
            preference = bound_int(request.form.get("preference_score", 5), "Preference", 0, 10)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("planner"))

        file_name = None
        file_text = ""
        uploaded = request.files.get("source_file")
        if uploaded and uploaded.filename:
            if not allowed_file(uploaded.filename):
                flash("Unsupported file type.")
                return redirect(url_for("planner"))
            file_name, save_path = save_upload(uploaded)
            file_text = extract_uploaded_text(save_path)

        difficulty = estimate_difficulty_from_text(title, file_text)
        priority_value = calculate_topic_priority(difficulty, preference)

        db.session.add(StudyTopic(
            module_id=module.id,
            title=title,
            difficulty_score=difficulty,
            preference_score=preference,
            priority_value=priority_value,
            source_file=file_name,
        ))
        db.session.commit()
        flash("Topic added.")
        return redirect(url_for("planner"))

    topics = (
        StudyTopic.query.join(Module, StudyTopic.module_id == Module.id)
        .filter(Module.user_id == current_user.id)
        .order_by(StudyTopic.priority_value.desc(), StudyTopic.id.asc())
        .all()
    )
    exams = (
        ExamEvent.query.join(Module, ExamEvent.module_id == Module.id)
        .filter(Module.user_id == current_user.id)
        .order_by(ExamEvent.exam_start_date.asc())
        .all()
    )
    plans = StudyPlan.query.filter_by(user_id=current_user.id).order_by(StudyPlan.exam_start_date.asc()).all()
    for plan in plans:
        reschedule_missed_items(plan)
    return render_template("planner.html", modules=modules_list, topics=topics, exams=exams, plans=plans)


@app.route("/planner/topic/<int:topic_id>/edit", methods=["GET", "POST"])
@login_required
def edit_topic(topic_id):
    topic = StudyTopic.query.get_or_404(topic_id)
    if topic.module.user_id != current_user.id:
        abort(403)
    if request.method == "POST":
        title = clean_text(request.form.get("title"))
        try:
            preference = bound_int(request.form.get("preference_score", 5), "Preference", 0, 10)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("edit_topic", topic_id=topic.id))
        if len(title) < 2 or len(title) > 200:
            flash("Topic title must be between 2 and 200 characters.")
            return redirect(url_for("edit_topic", topic_id=topic.id))
        uploaded = request.files.get("source_file")
        if uploaded and uploaded.filename:
            if not allowed_file(uploaded.filename):
                flash("Unsupported file type.")
                return redirect(url_for("edit_topic", topic_id=topic.id))
            file_name, save_path = save_upload(uploaded)
            topic.source_file = file_name
            topic.difficulty_score = estimate_difficulty_from_text(title, extract_uploaded_text(save_path))
        else:
            topic.difficulty_score = estimate_difficulty_from_text(title, "")
        topic.title = title
        topic.preference_score = preference
        topic.priority_value = calculate_topic_priority(topic.difficulty_score, preference)
        db.session.commit()
        flash("Topic updated.")
        return redirect(url_for("planner"))
    return render_template("topic_edit.html", topic=topic)


@app.route("/planner/topic/<int:topic_id>/delete", methods=["POST"])
@login_required
def delete_topic(topic_id):
    topic = StudyTopic.query.get_or_404(topic_id)
    if topic.module.user_id != current_user.id:
        abort(403)
    db.session.delete(topic)
    db.session.commit()
    flash("Topic deleted.")
    return redirect(url_for("planner"))


@app.route("/planner/generate/<int:exam_id>", methods=["POST"])
@login_required
def generate_plan(exam_id):
    exam = ExamEvent.query.get_or_404(exam_id)
    if exam.module.user_id != current_user.id:
        abort(403)
    if StudyPlan.query.filter_by(user_id=current_user.id, module_id=exam.module_id, exam_start_date=exam.exam_start_date, exam_end_date=exam.exam_end_date).first():
        flash("A plan already exists for this exam.")
        return redirect(url_for("planner"))
    plan = generate_study_plan_for_exam(
        current_user,
        exam.module_id,
        exam.exam_start_date,
        exam.exam_end_date,
        plan_name=f"{exam.module.code} {exam.exam_kind.title()} Exam Plan"
    )
    if not plan:
        flash("Add at least one topic for this module before generating a plan.")
        return redirect(url_for("planner"))
    flash("Study plan generated.")
    return redirect(url_for("planner"))


@app.route("/planner/<int:plan_id>/share", methods=["POST"])
@login_required
def share_plan(plan_id):
    plan = StudyPlan.query.get_or_404(plan_id)
    if plan.user_id != current_user.id:
        abort(403)
    plan.is_shared = True
    db.session.commit()
    flash("Plan shared.")
    return redirect(url_for("planner"))


@app.route("/planner/<int:plan_id>/reschedule", methods=["POST"])
@login_required
def reschedule_plan(plan_id):
    plan = StudyPlan.query.get_or_404(plan_id)
    if plan.user_id != current_user.id:
        abort(403)
    reschedule_missed_items(plan)
    flash("Plan rescheduled.")
    return redirect(url_for("planner"))


@app.route("/planner/item/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_plan_item(item_id):
    item = StudyPlanItem.query.get_or_404(item_id)
    if item.plan.user_id != current_user.id:
        abort(403)
    item.completed = not item.completed
    db.session.commit()
    return jsonify({"completed": item.completed})


@app.route("/groups")
@login_required
def groups():
    memberships = StudyGroupMember.query.filter_by(user_id=current_user.id).all()
    groups_data = [StudyGroup.query.get(m.group_id) for m in memberships]
    open_groups = StudyGroup.query.order_by(StudyGroup.exam_start_date.desc()).all()
    member_group_ids = [g.id for g in groups_data if g]
    return render_template("groups.html", memberships=groups_data, open_groups=open_groups, member_group_ids=member_group_ids)


@app.route("/groups/match")
@login_required
def match_groups():
    exams = ExamEvent.query.join(Module, ExamEvent.module_id == Module.id).filter(Module.user_id == current_user.id).all()
    for exam in exams:
        create_or_join_group_for_exam(exam.module, exam.exam_start_date, exam.exam_end_date, current_user)
    flash("Your exams were checked against compatible study groups.")
    return redirect(url_for("groups"))


@app.route("/groups/<int:group_id>")
@login_required
def group_detail(group_id):
    group = StudyGroup.query.get_or_404(group_id)
    member = StudyGroupMember.query.filter_by(group_id=group.id, user_id=current_user.id).first()
    if not member:
        flash("Join the group to see its resources and sessions.")
        return redirect(url_for("groups"))
    members = [User.query.get(m.user_id) for m in StudyGroupMember.query.filter_by(group_id=group.id).all()]
    members = [m for m in members if m]
    resources = Resource.query.filter_by(group_id=group.id).order_by(Resource.id.desc()).all()
    sessions = JointSession.query.filter_by(group_id=group.id).order_by(JointSession.session_date.asc()).all()
    shared_plans = StudyPlan.query.join(Module, StudyPlan.module_id == Module.id).filter(Module.code == group.module_code, StudyPlan.is_shared.is_(True)).all()
    return render_template(
        "group_detail.html",
        group=group,
        members=members,
        resources=resources,
        sessions=sessions,
        shared_plans=shared_plans
    )


@app.route("/groups/<int:group_id>/join", methods=["POST"])
@login_required
def join_group(group_id):
    group = StudyGroup.query.get_or_404(group_id)
    existing = StudyGroupMember.query.filter_by(group_id=group.id, user_id=current_user.id).first()
    if not existing:
        db.session.add(StudyGroupMember(group_id=group.id, user_id=current_user.id, role="member"))
        db.session.commit()
    flash("Joined group.")
    return redirect(url_for("group_detail", group_id=group.id))


@app.route("/groups/<int:group_id>/leave", methods=["POST"])
@login_required
def leave_group(group_id):
    group = StudyGroup.query.get_or_404(group_id)
    membership = StudyGroupMember.query.filter_by(group_id=group.id, user_id=current_user.id).first()
    if not membership:
        flash("You are not a member of that group.")
        return redirect(url_for("groups"))
    db.session.delete(membership)
    db.session.commit()
    flash("You left the group.")
    return redirect(url_for("groups"))


@app.route("/groups/<int:group_id>/resource", methods=["POST"])
@login_required
def upload_resource(group_id):
    group = StudyGroup.query.get_or_404(group_id)
    member = StudyGroupMember.query.filter_by(group_id=group.id, user_id=current_user.id).first()
    if not member:
        abort(403)
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        flash("Choose a file.")
        return redirect(url_for("group_detail", group_id=group.id))
    if not allowed_file(uploaded.filename):
        flash("Unsupported file type.")
        return redirect(url_for("group_detail", group_id=group.id))
    filename, path = save_upload(uploaded)
    db.session.add(Resource(
        group_id=group.id,
        uploaded_by=current_user.id,
        filename=filename,
        filepath=str(path)
    ))
    db.session.commit()
    flash("Resource uploaded.")
    return redirect(url_for("group_detail", group_id=group.id))


@app.route("/groups/<int:group_id>/session", methods=["POST"])
@login_required
def add_session(group_id):
    group = StudyGroup.query.get_or_404(group_id)
    member = StudyGroupMember.query.filter_by(group_id=group.id, user_id=current_user.id).first()
    if not member:
        abort(403)

    try:
        session_date = parse_date(request.form.get("session_date", ""), "Session date")
        if session_date < date.today():
            flash("Session date cannot be in the past.")
            return redirect(url_for("group_detail", group_id=group.id))
        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()
        start_dt = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")
        if end_dt <= start_dt:
            flash("End time must be after start time.")
            return redirect(url_for("group_detail", group_id=group.id))
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("group_detail", group_id=group.id))

    notes = clean_text(request.form.get("notes"))[:500]
    db.session.add(JointSession(
        group_id=group.id,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        notes=notes
    ))
    db.session.flush()

    member_rows = StudyGroupMember.query.filter_by(group_id=group.id).all()
    member_ids = [m.user_id for m in member_rows]
    plans_to_block = StudyPlan.query.filter(
        StudyPlan.user_id.in_(member_ids),
        StudyPlan.module_id == group.module_id,
    ).all()
    for plan in plans_to_block:
        note_text = f"Blocked for group session {start_time}-{end_time}"
        already_blocked = StudyPlanItem.query.filter_by(
            plan_id=plan.id,
            target_date=session_date,
            topic_id=None,
            note=note_text
        ).first()
        if not already_blocked:
            db.session.add(StudyPlanItem(
                plan_id=plan.id,
                topic_id=None,
                target_date=session_date,
                completed=False,
                note=note_text
            ))
    for member_row in member_rows:
        notify(member_row.user_id, "group", group.id, f"Joint session scheduled on {session_date.isoformat()}")
    db.session.commit()
    flash("Joint session created and blocked in shared plans.")
    return redirect(url_for("group_detail", group_id=group.id))


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


@app.route("/uploads/<path:filename>")
@login_required
def download_upload(filename):
    safe_name = re.split(r"[\/]+", filename)[-1]
    return send_from_directory(app.config["UPLOAD_FOLDER"], safe_name, as_attachment=True)


@app.route("/static/profile_pics/<path:filename>")
@login_required
def profile_pic(filename):
    return send_from_directory(Path(app.static_folder) / "profile_pics", filename)


@app.errorhandler(403)
def forbidden(_):
    return render_template("simple_message.html", title="Forbidden", message="You do not have access to this resource."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("simple_message.html", title="Not Found", message="The page you requested was not found."), 404


if __name__ == "__main__":
    init_folders()
    with app.app_context():
        db.create_all()
    try:
        start_scheduler()
    except Exception:
        pass
    app.run(debug=True)
