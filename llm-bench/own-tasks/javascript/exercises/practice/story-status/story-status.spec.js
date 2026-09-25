import { deriveStoryStatus, applyTaskUpdate } from './story-status';

const t = (id, status) => ({ id, status });

describe('deriveStoryStatus', () => {
  test('no tasks', () => {
    expect(deriveStoryStatus([])).toBe('IN_SPRINT');
  });

  test('only excluded tasks', () => {
    expect(deriveStoryStatus([t('a', 'excluded')])).toBe('IN_SPRINT');
  });

  test('all todo', () => {
    expect(deriveStoryStatus([t('a', 'todo'), t('b', 'todo')])).toBe('IN_SPRINT');
  });

  test('all done, excluded ignored', () => {
    expect(deriveStoryStatus([t('a', 'done'), t('b', 'excluded'), t('c', 'done')])).toBe('DONE');
  });

  test('failed wins over everything', () => {
    expect(deriveStoryStatus([t('a', 'done'), t('b', 'failed'), t('c', 'in_progress')])).toBe('FAILED');
  });

  test('in progress or review', () => {
    expect(deriveStoryStatus([t('a', 'todo'), t('b', 'review')])).toBe('IN_PROGRESS');
    expect(deriveStoryStatus([t('a', 'in_progress')])).toBe('IN_PROGRESS');
  });

  test('done plus todo is in progress', () => {
    expect(deriveStoryStatus([t('a', 'done'), t('b', 'todo')])).toBe('IN_PROGRESS');
  });

  test('unknown status throws', () => {
    expect(() => deriveStoryStatus([t('a', 'DONE')])).toThrow(Error);
  });
});

describe('applyTaskUpdate', () => {
  const story = () => ({ id: 's1', status: 'IN_SPRINT', tasks: [t('a', 'todo'), t('b', 'todo')] });

  test('updates task and derives story', () => {
    const next = applyTaskUpdate(story(), 'a', 'in_progress');
    expect(next.tasks.find((x) => x.id === 'a').status).toBe('in_progress');
    expect(next.status).toBe('IN_PROGRESS');
    expect(next.id).toBe('s1');
  });

  test('completing the last task marks story done', () => {
    const s = { id: 's1', status: 'IN_PROGRESS', tasks: [t('a', 'done'), t('b', 'review')] };
    expect(applyTaskUpdate(s, 'b', 'done', 'review').status).toBe('DONE');
  });

  test('does not mutate the input', () => {
    const s = story();
    const snapshot = JSON.parse(JSON.stringify(s));
    const tasksRef = s.tasks;
    const taskA = s.tasks[0];
    const next = applyTaskUpdate(s, 'a', 'done');
    expect(s).toEqual(snapshot);
    expect(s.tasks).toBe(tasksRef);
    expect(next).not.toBe(s);
    expect(next.tasks).not.toBe(tasksRef);
    expect(next.tasks[0]).not.toBe(taskA);
  });

  test('untouched tasks keep identity', () => {
    const s = story();
    const next = applyTaskUpdate(s, 'a', 'done');
    expect(next.tasks[1]).toBe(s.tasks[1]);
  });

  test('keeps task order', () => {
    const next = applyTaskUpdate(story(), 'b', 'done');
    expect(next.tasks.map((x) => x.id)).toEqual(['a', 'b']);
  });

  test('unknown task', () => {
    expect(() => applyTaskUpdate(story(), 'zz', 'done')).toThrow(/not found/);
  });

  test('invalid status', () => {
    expect(() => applyTaskUpdate(story(), 'a', 'finished')).toThrow(/invalid status/);
  });

  test('expected status conflict', () => {
    expect(() => applyTaskUpdate(story(), 'a', 'done', 'in_progress')).toThrow(/conflict/);
  });

  test('expected status match', () => {
    expect(applyTaskUpdate(story(), 'a', 'failed', 'todo').status).toBe('FAILED');
  });
});
