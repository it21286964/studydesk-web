from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    program = db.Column(db.String(120), default="")
    location_pref = db.Column(db.String(120), default="")
    availability = db.Column(db.String(255), default="")
    study_goal = db.Column(db.String(255), default="")
    profile_picture = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    modules = db.relationship("Module", backref="owner", lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="recipient", lazy=True, cascade="all, delete-orphan")


class Module(db.Model):
    __tablename__ = "modules"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    credits = db.Column(db.Integer, default=0)

    assignments = db.relationship("Assignment", backref="module", lazy=True, cascade="all, delete-orphan")
    exams = db.relationship("ExamEvent", backref="module", lazy=True, cascade="all, delete-orphan")
    topics = db.relationship("StudyTopic", backref="module", lazy=True, cascade="all, delete-orphan")
    plans = db.relationship("StudyPlan", backref="module", lazy=True, cascade="all, delete-orphan")
    groups = db.relationship("StudyGroup", backref="module", lazy=True, cascade="all, delete-orphan")


class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(30), nullable=False)
    deadline = db.Column(db.DateTime, nullable=False, index=True)
    credit_weight = db.Column(db.Integer, default=0)
    priority_level = db.Column(db.Integer, default=1)
    status = db.Column(db.String(30), default="Not Started")
    exam_kind = db.Column(db.String(20), default="")
    exam_start_date = db.Column(db.Date, nullable=True)
    exam_end_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ExamEvent(db.Model):
    __tablename__ = "exam_events"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id"), nullable=False, index=True)
    module_code = db.Column(db.String(20), nullable=False, index=True)
    exam_kind = db.Column(db.String(20), default="mid")
    exam_start_date = db.Column(db.Date, nullable=False, index=True)
    exam_end_date = db.Column(db.Date, nullable=False, index=True)
    created_from_assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=True)


class StudyTopic(db.Model):
    __tablename__ = "study_topics"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    difficulty_score = db.Column(db.Integer, default=5)
    preference_score = db.Column(db.Integer, default=5)
    priority_value = db.Column(db.Integer, default=0, index=True)
    source_file = db.Column(db.String(255), nullable=True)


class StudyPlan(db.Model):
    __tablename__ = "study_plans"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id"), nullable=False, index=True)
    exam_start_date = db.Column(db.Date, nullable=False)
    exam_end_date = db.Column(db.Date, nullable=False)
    plan_name = db.Column(db.String(200), nullable=False)
    is_shared = db.Column(db.Boolean, default=False)

    items = db.relationship("StudyPlanItem", backref="plan", lazy=True, cascade="all, delete-orphan", order_by="StudyPlanItem.target_date")


class StudyPlanItem(db.Model):
    __tablename__ = "study_plan_items"
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("study_plans.id"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("study_topics.id"), nullable=True)
    target_date = db.Column(db.Date, nullable=False, index=True)
    completed = db.Column(db.Boolean, default=False)
    note = db.Column(db.String(255), default="")

    topic = db.relationship("StudyTopic", backref="plan_items")


class StudyGroup(db.Model):
    __tablename__ = "study_groups"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id"), nullable=False, index=True)
    module_code = db.Column(db.String(20), nullable=False, index=True)
    exam_start_date = db.Column(db.Date, nullable=False, index=True)
    exam_end_date = db.Column(db.Date, nullable=False, index=True)
    location_pref = db.Column(db.String(120), default="")
    group_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), default="open")


class StudyGroupMember(db.Model):
    __tablename__ = "study_group_members"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("study_groups.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(30), default="member")


class Resource(db.Model):
    __tablename__ = "resources"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("study_groups.id"), nullable=False, index=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(255), nullable=False)
    uploader = db.relationship("User", backref="uploaded_resources")


class JointSession(db.Model):
    __tablename__ = "joint_sessions"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("study_groups.id"), nullable=False, index=True)
    session_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.String(10), nullable=False)
    end_time = db.Column(db.String(10), nullable=False)
    notes = db.Column(db.Text, default="")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_type = db.Column(db.String(30), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
