document.addEventListener("click", async (e) => {
  const statusBtn = e.target.closest(".status-btn");
  if (statusBtn) {
    const id = statusBtn.dataset.id;
    const res = await fetch(`/api/assignment/${id}/cycle`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      statusBtn.textContent = data.status;
      statusBtn.classList.remove("status-not-started", "status-in-progress", "status-submitted", "status-completed");
      statusBtn.classList.add(data.class || "status-not-started");
    }
    return;
  }

  const mini = e.target.closest(".mini-status-btn");
  if (mini) {
    const itemId = mini.dataset.planItem;
    const res = await fetch(`/planner/item/${itemId}/toggle`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      mini.textContent = data.completed ? "Done" : "Open";
      mini.classList.toggle("status-completed", data.completed);
      mini.classList.toggle("status-not-started", !data.completed);
    }
    return;
  }

  const notif = e.target.closest("[data-notification-id]");
  if (notif) {
    const id = notif.dataset.notificationId;
    await fetch(`/notifications/${id}/read`, { method: "POST" });
    notif.classList.remove("unread");
    notif.classList.add("read");
    return;
  }

  const markAll = e.target.closest("[data-mark-all-read]");
  if (markAll) {
    await fetch("/notifications/read-all", { method: "POST" });
    document.querySelectorAll("[data-notification-id]").forEach((el) => {
      el.classList.remove("unread");
      el.classList.add("read");
    });
  }
});

document.addEventListener("input", (e) => {
  const input = e.target.closest("[data-live-filter]");
  if (input) {
    const selector = input.dataset.liveFilter;
    const query = input.value.trim().toLowerCase();
    document.querySelectorAll(selector).forEach((row) => {
      const text = row.textContent.toLowerCase();
      const typeFilter = document.querySelector("[data-live-filter-by]");
      let typeOk = true;
      if (typeFilter && typeFilter.value) {
        const field = typeFilter.dataset.liveFilterField || "type";
        typeOk = (row.dataset[field] || "").toLowerCase() === typeFilter.value.toLowerCase();
      }
      row.style.display = text.includes(query) && typeOk ? "" : "none";
    });
    return;
  }

  const typeFilter = e.target.closest("[data-live-filter-by]");
  if (typeFilter) {
    const selector = typeFilter.dataset.liveFilterBy;
    const queryInput = document.querySelector("[data-live-filter]");
    const query = queryInput ? queryInput.value.trim().toLowerCase() : "";
    document.querySelectorAll(selector).forEach((row) => {
      const text = row.textContent.toLowerCase();
      const field = typeFilter.dataset.liveFilterField || "type";
      const typeOk = !typeFilter.value || (row.dataset[field] || "").toLowerCase() === typeFilter.value.toLowerCase();
      row.style.display = text.includes(query) && typeOk ? "" : "none";
    });
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const today = new Date();
  const isoToday = today.toISOString().slice(0, 10);
  document.querySelectorAll(".future-date, [data-future-date]").forEach((input) => {
    if (!input.min) input.min = isoToday;
  });

  const taskType = document.querySelector("#task-type");
  const examExtra = document.querySelector("#exam-extra");
  const deadlineField = document.querySelector("#deadline-field");
  const deadlineInput = deadlineField ? deadlineField.querySelector('input[name="deadline"]') : null;
  const syncExamVisibility = () => {
    if (!taskType || !examExtra) return;
    const isExam = taskType.value === "exam";
    examExtra.classList.toggle("show", isExam);
    examExtra.querySelectorAll("input, select").forEach((el) => {
      el.required = isExam;
    });
    if (deadlineField && deadlineInput) {
      deadlineField.classList.toggle("hidden-section", isExam);
      deadlineInput.required = !isExam;
      deadlineInput.disabled = isExam;
      if (isExam) deadlineInput.value = "";
    }
  };
  if (taskType && examExtra) {
    taskType.addEventListener("change", syncExamVisibility);
    syncExamVisibility();
  }

  const newPassword = document.querySelector('input[name="new_password"]');
  const confirmPassword = document.querySelector('input[name="confirm_password"]');
  if (newPassword && confirmPassword) {
    const syncPasswordMatch = () => {
      if (confirmPassword.value && newPassword.value !== confirmPassword.value) {
        confirmPassword.setCustomValidity("Passwords do not match.");
      } else {
        confirmPassword.setCustomValidity("");
      }
    };
    newPassword.addEventListener("input", syncPasswordMatch);
    confirmPassword.addEventListener("input", syncPasswordMatch);
  }

  const startTime = document.querySelector('input[name="start_time"]');
  const endTime = document.querySelector('input[name="end_time"]');
  if (startTime && endTime) {
    const syncSessionTime = () => {
      if (startTime.value && endTime.value && endTime.value <= startTime.value) {
        endTime.setCustomValidity("End time must be after start time.");
      } else {
        endTime.setCustomValidity("");
      }
    };
    startTime.addEventListener("input", syncSessionTime);
    endTime.addEventListener("input", syncSessionTime);
  }
});
