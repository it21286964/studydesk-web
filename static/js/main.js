document.addEventListener("click", async (e) => {
  const statusBtn = e.target.closest(".status-btn");
  if (statusBtn) {
    const id = statusBtn.dataset.id;
    const res = await fetch(`/api/assignment/${id}/cycle`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      statusBtn.textContent = data.status;
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
  if (!input) return;
  const selector = input.dataset.liveFilter;
  const query = input.value.trim().toLowerCase();
  document.querySelectorAll(selector).forEach((row) => {
    const text = row.textContent.toLowerCase();
    row.style.display = text.includes(query) ? "" : "none";
  });
});
document.addEventListener("DOMContentLoaded", () => {
  const futureDates = document.querySelectorAll("[data-future-date]");
  const today = new Date();
  const isoToday = today.toISOString().slice(0, 10);
  futureDates.forEach((input) => {
    if (!input.min) input.min = isoToday;
  });

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

