import { summarize } from './envelope-log';

const e = (id, status, previous_status = null) => JSON.stringify({ id, status, previous_status });

describe('summarize', () => {
  test('empty log', () => {
    expect(summarize([])).toEqual({ statuses: {}, illegal: [], gaps: [], malformed: 0, requeues: {} });
  });

  test('happy path', () => {
    const r = summarize([e('a', 'pending'), e('a', 'claimed', 'pending'), e('a', 'done', 'claimed')]);
    expect(r.statuses).toEqual({ a: 'done' });
    expect(r.illegal).toEqual([]);
    expect(r.gaps).toEqual([]);
  });

  test('requeue counted', () => {
    const r = summarize([
      e('a', 'pending'), e('a', 'claimed', 'pending'), e('a', 'pending', 'claimed'),
      e('a', 'claimed', 'pending'), e('a', 'pending', 'claimed'), e('b', 'pending'),
    ]);
    expect(r.statuses).toEqual({ a: 'pending', b: 'pending' });
    expect(r.requeues).toEqual({ a: 2 });
  });

  test('illegal transitions are recorded and not applied', () => {
    const r = summarize([
      e('a', 'pending'), e('a', 'claimed', 'pending'), e('a', 'done', 'claimed'),
      e('a', 'claimed', 'done'), e('b', 'done', 'pending'),
    ]);
    expect(r.statuses).toEqual({ a: 'done' });
    expect(r.illegal).toEqual([{ id: 'a', from: 'done', to: 'claimed' }, { id: 'b', from: 'pending', to: 'done' }]);
  });

  test('missing previous_status means creation', () => {
    const r = summarize([JSON.stringify({ id: 'a', status: 'pending' })]);
    expect(r.statuses).toEqual({ a: 'pending' });
    expect(r.gaps).toEqual([]);
  });

  test('gap detected when an event was missed', () => {
    const r = summarize([e('a', 'pending'), e('a', 'done', 'claimed'), e('b', 'claimed', 'pending'), e('b', 'done', 'claimed')]);
    expect(r.statuses).toEqual({ a: 'done', b: 'done' });
    expect(r.gaps).toEqual(['a', 'b']);
  });

  test('gap listed once per id', () => {
    const r = summarize([e('a', 'claimed', 'pending'), e('a', 'cancelled', 'pending')]);
    expect(r.gaps).toEqual(['a']);
    expect(r.statuses).toEqual({ a: 'cancelled' });
  });

  test('malformed lines are counted and skipped', () => {
    const r = summarize(['not json', '[]', 'null', '42', JSON.stringify({ id: 1, status: 'pending' }),
      JSON.stringify({ id: 'x' }), e('a', 'pending'), '{"id":"b","status":"pending"']);
    expect(r.malformed).toBe(7);
    expect(r.statuses).toEqual({ a: 'pending' });
  });

  test('re-creation of a known message is a gap, not illegal', () => {
    const r = summarize([e('a', 'pending'), e('a', 'pending')]);
    expect(r.illegal).toEqual([]);
    expect(r.gaps).toEqual(['a']);
  });

  test('unknown statuses are illegal', () => {
    const r = summarize([e('a', 'archived', 'done'), e('b', 'pending'), e('b', 'weird', 'pending')]);
    expect(r.illegal).toEqual([{ id: 'a', from: 'done', to: 'archived' }, { id: 'b', from: 'pending', to: 'weird' }]);
    expect(r.statuses).toEqual({ b: 'pending' });
  });
});
