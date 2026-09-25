const CODE = /^S-(\d{4})-(\d{2})-(\d{2})-([1-9]\d*)$/;

const isCalendarDate = (y, m, d) => {
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
};

export const nextSprintCode = (existingCodes, date) => {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
    throw new Error('invalid date');
  }
  const day = date.toISOString().slice(0, 10);
  let max = 0;
  for (const code of existingCodes) {
    if (typeof code !== 'string') continue;
    const m = CODE.exec(code);
    if (!m) continue;
    const [, y, mo, d, n] = m;
    if (!isCalendarDate(+y, +mo, +d)) continue;
    if (`${y}-${mo}-${d}` === day) max = Math.max(max, Number(n));
  }
  return `S-${day}-${max + 1}`;
};
