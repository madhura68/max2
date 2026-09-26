const ALLOWED = {
  null: ['pending'],
  pending: ['claimed', 'cancelled'],
  claimed: ['done', 'failed', 'pending', 'cancelled'],
};

const parse = (line) => {
  try {
    const v = JSON.parse(line);
    if (v && typeof v === 'object' && !Array.isArray(v) && typeof v.id === 'string' && typeof v.status === 'string') {
      return v;
    }
  } catch {
    // fall through
  }
  return null;
};

export const summarize = (lines) => {
  const statuses = {};
  const illegal = [];
  const gaps = [];
  const requeues = {};
  let malformed = 0;
  for (const line of lines) {
    const env = parse(line);
    if (!env) {
      malformed += 1;
      continue;
    }
    const from = env.previous_status === undefined ? null : env.previous_status;
    const { id, status: to } = env;
    if (!(ALLOWED[from] || []).includes(to)) {
      illegal.push({ id, from, to });
      continue;
    }
    const known = Object.prototype.hasOwnProperty.call(statuses, id) ? statuses[id] : null;
    if (known !== from && !gaps.includes(id)) gaps.push(id);
    statuses[id] = to;
    if (from === 'claimed' && to === 'pending') requeues[id] = (requeues[id] || 0) + 1;
  }
  return { statuses, illegal, gaps, malformed, requeues };
};
