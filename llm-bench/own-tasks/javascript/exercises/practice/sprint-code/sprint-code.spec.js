import { nextSprintCode } from './sprint-code';

const d = (s) => new Date(s);

describe('nextSprintCode', () => {
  test('first sprint of the day', () => {
    expect(nextSprintCode([], d('2026-09-25T10:00:00Z'))).toBe('S-2026-09-25-1');
  });

  test('counts per date', () => {
    const codes = ['S-2026-09-24-1', 'S-2026-09-24-2', 'S-2026-09-25-1'];
    expect(nextSprintCode(codes, d('2026-09-25T10:00:00Z'))).toBe('S-2026-09-25-2');
  });

  test('gaps are not reused', () => {
    expect(nextSprintCode(['S-2026-09-25-1', 'S-2026-09-25-3'], d('2026-09-25T00:00:00Z'))).toBe('S-2026-09-25-4');
  });

  test('numeric not lexical maximum', () => {
    expect(nextSprintCode(['S-2026-09-25-9', 'S-2026-09-25-10'], d('2026-09-25T00:00:00Z'))).toBe('S-2026-09-25-11');
  });

  test('uses the UTC date', () => {
    expect(nextSprintCode([], new Date(Date.UTC(2026, 0, 5, 23, 30)))).toBe('S-2026-01-05-1');
    expect(nextSprintCode([], d('2026-01-05T23:30:00-05:00'))).toBe('S-2026-01-06-1');
  });

  test('ignores junk codes', () => {
    const codes = ['S-2026-09-25-0', 'S-2026-09-25-01', 's-2026-09-25-7', 'S-2026-09-25-8x',
      'X-2026-09-25-9', 'S-2026-9-25-5', null, undefined, 42, ' S-2026-09-25-6', 'S-2026-09-25-2'];
    expect(nextSprintCode(codes, d('2026-09-25T00:00:00Z'))).toBe('S-2026-09-25-3');
  });

  test('ignores impossible calendar dates', () => {
    const codes = ['S-2026-02-30-4', 'S-2026-13-01-4', 'S-2026-02-28-1'];
    expect(nextSprintCode(codes, d('2026-02-28T12:00:00Z'))).toBe('S-2026-02-28-2');
  });

  test('leap day', () => {
    expect(nextSprintCode(['S-2028-02-29-1'], d('2028-02-29T00:00:00Z'))).toBe('S-2028-02-29-2');
  });

  test('invalid date throws', () => {
    expect(() => nextSprintCode([], new Date('nope'))).toThrow(Error);
    expect(() => nextSprintCode([], '2026-09-25')).toThrow(Error);
  });

  test('does not mutate input', () => {
    const codes = ['S-2026-09-25-1'];
    nextSprintCode(codes, d('2026-09-25T00:00:00Z'));
    expect(codes).toEqual(['S-2026-09-25-1']);
  });
});
