import { useAdminQuery, formatTime } from './hooks';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { Temporal } from '@js-temporal/polyfill';
import { Plus, X } from 'lucide-react';
import { Button } from '@/shared/ui/Button';
import { PageTitle } from '@/shared/ui/PageTitle';
import { useAccountSession } from '@/features/accounts/session';
import type { HoursInput, ScheduleUpdate } from '@/shared/api/generated/types.gen';
import { adminApi, type Impact, type Schedule } from './api';
import { ConfirmAction, ErrorNotice, QueryState, ReasonField } from './shared';

const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
function clock(minute: number) {
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
}
function local(value: string) {
  return Temporal.Instant.from(value)
    .toZonedDateTimeISO('Australia/Melbourne')
    .toPlainDateTime()
    .toString({ smallestUnit: 'minute' });
}
function closureInstant(value: string) {
  return Temporal.PlainDateTime.from(value)
    .toZonedDateTime('Australia/Melbourne', { disambiguation: 'reject' })
    .toInstant()
    .toString();
}
function Windows({
  value,
  onChange,
  label,
}: {
  value: HoursInput[];
  onChange: (windows: HoursInput[]) => void;
  label: string;
}) {
  return (
    <div className="ad-windows">
      {!value.length && <span className="ad-hint">Closed</span>}
      {value.map((window, i) => (
        <div className="ad-window" key={i}>
          <label>
            <span className="ad-sr-only">
              {label} opening {i + 1}
            </span>
            <select
              aria-label={`${label} opening ${i + 1}`}
              value={window.start_minute}
              onChange={(e) =>
                onChange(
                  value.map((w, j) =>
                    j === i ? { ...w, start_minute: Number(e.target.value) } : w,
                  ),
                )
              }
            >
              {Array.from({ length: 96 }, (_, n) => (
                <option key={n} value={n * 15}>
                  {clock(n * 15)}
                </option>
              ))}
            </select>
          </label>
          <span aria-hidden="true">to</span>
          <label>
            <span className="ad-sr-only">
              {label} closing {i + 1}
            </span>
            <select
              aria-label={`${label} closing ${i + 1}`}
              value={window.end_minute}
              onChange={(e) =>
                onChange(
                  value.map((w, j) => (j === i ? { ...w, end_minute: Number(e.target.value) } : w)),
                )
              }
            >
              {Array.from({ length: 96 }, (_, n) => (
                <option key={n} value={(n + 1) * 15}>
                  {clock((n + 1) * 15)}
                </option>
              ))}
            </select>
          </label>
          <Button
            aria-label={`Remove ${label} window ${i + 1}`}
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      ))}
      <Button
        disabled={value.length >= 16}
        onClick={() => onChange([...value, { start_minute: 540, end_minute: 1020 }])}
      >
        <Plus aria-hidden="true" /> Add hours
      </Button>
    </div>
  );
}
export function SchedulePage() {
  const { roomId = '' } = useParams();
  const schedule = useAdminQuery(
    ['schedule', roomId],
    (signal) => adminApi.schedule(roomId, signal),
    false,
    false,
  );
  const room = useAdminQuery(
    ['room', roomId],
    (signal) => adminApi.room(roomId, signal),
    false,
    false,
  );
  return (
    <QueryState
      pending={schedule.isPending || room.isPending}
      error={schedule.error || room.error}
      retry={() => {
        void schedule.refetch();
        void room.refetch();
      }}
    >
      {schedule.data && room.data && (
        <ScheduleForm key={roomId} initial={schedule.data} name={room.data.name} />
      )}
    </QueryState>
  );
}
function ScheduleForm({ initial: seed, name }: { initial: Schedule; name: string }) {
  const [initial] = useState(seed);
  const session = useAccountSession();
  const navigate = useNavigate();
  const [weekly, setWeekly] = useState(initial.weekly);
  const [exceptions, setExceptions] = useState(initial.exceptions);
  const [closures, setClosures] = useState(
    initial.closures.map((c) => ({
      ...c,
      starts_at: local(c.starts_at),
      ends_at: local(c.ends_at),
    })),
  );
  const [confirmed, setConfirmed] = useState(initial.hours_confirmed);
  const [reason, setReason] = useState('');
  const [review, setReview] = useState<{ body: ScheduleUpdate; impact: Impact } | null>(null);
  const preview = useMutation({
    mutationFn: async () => {
      const body: ScheduleUpdate = {
        kind: 'schedule',
        revision: initial.revision,
        hours_confirmed: confirmed,
        weekly,
        exceptions,
        reason,
        closures: closures.map((c) => ({
          ...c,
          starts_at: closureInstant(c.starts_at),
          ends_at: closureInstant(c.ends_at),
        })),
      };
      return {
        body,
        impact: await adminApi.impact(initial.room_id, body, session.data?.csrf_token ?? ''),
      };
    },
    onSuccess: setReview,
  });
  return (
    <section>
      <Link className="ad-back" to="/admin/schedules">
        ← All schedules
      </Link>
      <PageTitle
        title={`${name} hours`}
        description="Australia/Melbourne · Date overrides replace that day’s weekly hours."
      />
      <form
        className="ad-form"
        onSubmit={(e) => {
          e.preventDefault();
          preview.mutate();
        }}
      >
        <section className="ad-panel">
          <div className="ad-section-head">
            <div>
              <span className="ad-eyebrow">The usual week</span>
              <h2>Weekly opening hours</h2>
            </div>
          </div>
          {days.map((day, weekday) => (
            <div className="ad-weekday" key={day}>
              <strong>{day}</strong>
              <Windows
                label={day}
                value={weekly.filter((w) => w.weekday === weekday)}
                onChange={(windows) =>
                  setWeekly([
                    ...weekly.filter((w) => w.weekday !== weekday),
                    ...windows.map((w) => ({ ...w, weekday })),
                  ])
                }
              />
            </div>
          ))}
        </section>
        <section className="ad-panel">
          <div className="ad-section-head">
            <div>
              <span className="ad-eyebrow">A different kind of day</span>
              <h2>Date overrides</h2>
            </div>
            <Button
              disabled={exceptions.length >= 366}
              onClick={() => setExceptions([...exceptions, { date: '', windows: [] }])}
            >
              <Plus aria-hidden="true" /> Add date
            </Button>
          </div>
          <p className="ad-hint">No opening windows means closed for the whole date.</p>
          {!exceptions.length && <p>No date overrides. Weekly hours apply.</p>}
          {exceptions.map((exception, i) => (
            <fieldset className="ad-override" key={i}>
              <legend>Override {i + 1}</legend>
              <div className="ad-section-head">
                <label className="ad-field">
                  Date
                  <input
                    type="date"
                    required
                    value={exception.date}
                    onChange={(e) =>
                      setExceptions(
                        exceptions.map((item, j) =>
                          j === i ? { ...item, date: e.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
                <Button
                  aria-label={`Remove override ${i + 1}`}
                  onClick={() => setExceptions(exceptions.filter((_, j) => j !== i))}
                >
                  Remove
                </Button>
              </div>
              <Windows
                label={`Override ${i + 1}`}
                value={exception.windows}
                onChange={(windows) =>
                  setExceptions(
                    exceptions.map((item, j) => (j === i ? { ...item, windows } : item)),
                  )
                }
              />
            </fieldset>
          ))}
        </section>
        <section className="ad-panel">
          <div className="ad-section-head">
            <div>
              <span className="ad-eyebrow">Time out</span>
              <h2>Temporary closures</h2>
            </div>
            <Button
              disabled={closures.length >= 500}
              onClick={() => setClosures([...closures, { starts_at: '', ends_at: '', reason: '' }])}
            >
              <Plus aria-hidden="true" /> Add closure
            </Button>
          </div>
          <p className="ad-hint">
            For maintenance or other times when the room cannot be booked. Ambiguous daylight-saving
            times are rejected.
          </p>
          {!closures.length && <p>No temporary closures.</p>}
          {closures.map((closure, i) => (
            <fieldset className="ad-override" key={i}>
              <legend>Closure {i + 1}</legend>
              <div className="ad-form-columns">
                <label className="ad-field">
                  Starts
                  <input
                    type="datetime-local"
                    step={900}
                    required
                    value={closure.starts_at}
                    onChange={(e) =>
                      setClosures(
                        closures.map((item, j) =>
                          j === i ? { ...item, starts_at: e.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
                <label className="ad-field">
                  Ends
                  <input
                    type="datetime-local"
                    step={900}
                    required
                    value={closure.ends_at}
                    onChange={(e) =>
                      setClosures(
                        closures.map((item, j) =>
                          j === i ? { ...item, ends_at: e.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
              </div>
              <label className="ad-field">
                Closure reason
                <input
                  required
                  maxLength={500}
                  value={closure.reason}
                  onChange={(e) =>
                    setClosures(
                      closures.map((item, j) =>
                        j === i ? { ...item, reason: e.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <Button onClick={() => setClosures(closures.filter((_, j) => j !== i))}>
                Remove closure {i + 1}
              </Button>
            </fieldset>
          ))}
        </section>
        <section className="ad-panel">
          <label className="ad-check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{' '}
            I confirm these opening hours are correct
          </label>
          <ReasonField value={reason} onChange={setReason} />
          <ErrorNotice error={preview.error} />
          {preview.error && (
            <p>
              <Link reloadDocument to={`/admin/schedules/${initial.room_id}`}>
                Reload the latest schedule
              </Link>{' '}
              to resolve a revision conflict. Unsaved changes will be discarded.
            </p>
          )}
          <div className="ad-actions">
            <Link to="/admin/schedules">Cancel</Link>
            <Button variant="primary" type="submit" disabled={preview.isPending}>
              {preview.isPending ? 'Checking bookings…' : 'Preview schedule change'}
            </Button>
          </div>
        </section>
      </form>
      {review &&
        (review.impact.affected_count ? (
          <div className="ad-error" role="alert">
            <h2>{review.impact.affected_count} booking(s) affected</h2>
            <p>This schedule cannot be saved until affected bookings are resolved.</p>
            <ul>
              {review.impact.affected_bookings.map((b) => (
                <li key={b.id}>
                  {b.owner_label} · {formatTime(b.starts_at)} – {formatTime(b.ends_at)}
                </li>
              ))}
            </ul>
            <Link to={`/admin/bookings?room_id=${initial.room_id}`}>Review room bookings →</Link>
            <Button onClick={() => setReview(null)}>Keep editing</Button>
          </div>
        ) : (
          <ConfirmAction
            title="Save this schedule?"
            intent={{ action: 'schedule.update', target: initial.room_id, payload: review.body }}
            onClose={() => setReview(null)}
            onSuccess={() => {
              void navigate('/admin/schedules');
            }}
            action={(csrf, key) => adminApi.updateSchedule(initial.room_id, review.body, csrf, key)}
          >
            <p>
              <strong>{name}</strong> · {review.body.weekly.length} weekly windows ·{' '}
              {review.body.exceptions.length} date overrides · {review.body.closures.length}{' '}
              closures
            </p>
            <p>
              No bookings are affected by this preview. Availability is checked again when you save.
            </p>
            <p>Reason: {review.body.reason}</p>
          </ConfirmAction>
        ))}
    </section>
  );
}
