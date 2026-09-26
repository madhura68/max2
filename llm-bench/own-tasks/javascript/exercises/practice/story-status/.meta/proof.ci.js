const VALID = new Set(['todo', 'in_progress', 'review', 'done', 'failed', 'excluded']);

export const deriveStoryStatus = (tasks) => {
  for (const task of tasks) {
    if (!VALID.has(task.status)) throw new Error(`invalid status ${task.status}`);
  }
  const live = tasks.filter((x) => x.status !== 'excluded').map((x) => x.status);
  if (live.length === 0) return 'IN_SPRINT';
  if (live.includes('failed')) return 'FAILED';
  if (live.every((s) => s === 'done')) return 'DONE';
  if (live.some((s) => s !== 'todo')) return 'IN_PROGRESS';
  return 'IN_SPRINT';
};

export const applyTaskUpdate = (story, taskId, status, expectedStatus) => {
  if (!VALID.has(status)) throw new Error(`invalid status ${status}`);
  const current = story.tasks.find((x) => x.id === taskId);
  if (!current) throw new Error(`task ${taskId} not found`);
  if (expectedStatus !== undefined && current.status !== expectedStatus) {
    throw new Error(`conflict: task ${taskId} is ${current.status}`);
  }
  const tasks = story.tasks.map((x) => (x.id === taskId ? { ...x, status } : x));
  return { ...story, tasks, status: deriveStoryStatus(tasks) };
};
