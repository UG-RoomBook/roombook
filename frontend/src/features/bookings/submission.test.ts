import { describe, expect, it, vi } from 'vitest';
import { attemptSlot, loadAttempt, saveAttempt } from './submission';

const ownerId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const body = {
  room_id: '11111111-1111-4111-8111-111111111111',
  starts_at: '2026-10-23T13:00:00+11:00',
  ends_at: '2026-10-23T14:00:00+11:00',
};
const attempt = {
  ownerId,
  body,
  key: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  state: 'pending' as const,
};

describe('durable booking attempt', () => {
  it('retains the same key through reload-equivalent reads and isolates users and intervals', () => {
    saveAttempt(attempt);
    expect(loadAttempt(ownerId, body)).toEqual(attempt);
    expect(loadAttempt('cccccccc-cccc-4ccc-8ccc-cccccccccccc', body)).toBeNull();
    expect(loadAttempt(ownerId, { ...body, ends_at: '2026-10-23T15:00:00+11:00' })).toBeNull();
    expect(sessionStorage.getItem(attemptSlot(ownerId, body))).not.toMatch(/csrf|password|token/);
  });
  it('does not silently replace a corrupt or mismatched saved attempt', () => {
    const slot = attemptSlot(ownerId, body);
    sessionStorage.setItem(slot, '{broken');
    expect(() => loadAttempt(ownerId, body)).toThrow(/could not be read/);
    sessionStorage.setItem(
      slot,
      JSON.stringify({ ...attempt, ownerId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' }),
    );
    expect(() => loadAttempt(ownerId, body)).toThrow(/could not be read/);
  });
  it('fails closed before submission when durable storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Quota exceeded');
    });
    expect(() => saveAttempt(attempt)).toThrow(/cannot save/);
  });
});
