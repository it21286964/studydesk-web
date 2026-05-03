# StudyDesk

StudyDesk is a compact Flask academic workload tracker with three connected modules:

- Assignments & Tasks Management
- Study Session Management
- Study Group Management

## What it does

- Register/login/logout
- Edit your profile details and password
- Add modules
- Add assignments, labs, quizzes, exams, and projects
- Cycle status with one tap: Not Started → In Progress → Submitted → Completed
- Automatically create exam anchors for the planner
- Score topics with Gemini 2.5 Flash when `GEMINI_API_KEY` is available, and fall back safely when it is not
- Upload PDFs and slide files to topics or group spaces
- Share study plans with groups
- Auto-match study groups by module code, exam date, availability, location preference, and study goal
- Create joint sessions that block shared and member study plans
- Receive reminders at 7 days, 24 hours, and 2 hours before deadlines

## Run it locally

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project folder:

```bash
SECRET_KEY=change-me
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

4. Run the app:

```bash
python app.py
```

The app uses a local SQLite database by default, so no database server is required.
