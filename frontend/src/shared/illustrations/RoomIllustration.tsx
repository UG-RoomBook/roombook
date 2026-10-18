import { useId } from 'react';
import { roomVisualDetails, type IllustratedRoom } from './room-visual-details';

function Chair({ id, x, y, scale = 1 }: { id: string; x: number; y: number; scale?: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`}>
      <ellipse cx="2" cy="31" rx="29" ry="7" fill="var(--shadow-ink)" opacity=".13" />
      <path
        d="M-15 7L-17 31M16 5L18 29"
        stroke="var(--metal)"
        strokeWidth="3.2"
        strokeLinecap="round"
      />
      <path
        d="M-23-20Q-23-26-16-27L17-30Q24-30 24-23L24-3Q24 4 16 5L-16 8Q-23 8-23 1Z"
        fill={`url(#${id}-seat)`}
      />
      <path d="M-23-4Q0 2 24-9L24-3Q24 4 16 5L-16 8Q-23 8-23 1Z" fill="var(--seat-side)" />
      <path d="M-21 4L19 0L28 9Q30 15 22 17L-16 21Q-23 21-25 16Z" fill="var(--seat-top)" />
      <path
        d="M-25 14Q-3 19 28 9L28 14Q28 19 21 20L-16 24Q-23 24-25 18Z"
        fill="var(--seat-bottom)"
      />
      <path d="M-17-22L17-25" stroke="var(--paper)" strokeWidth="1.4" opacity=".28" />
    </g>
  );
}

/** Approved v1 geometry; only instance IDs and material colours vary. */
export function RoomIllustration({
  room,
  className = '',
}: {
  room: IllustratedRoom;
  className?: string;
}) {
  const instanceId = useId();
  const id = `room-art-${instanceId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const { forum, code } = roomVisualDetails(room);
  return (
    <div className={`sw-visual ${forum ? 'alt' : ''} ${className}`.trim()} aria-hidden="true">
      {code && <span className="sw-number">{code}</span>}
      <svg
        className="sw-room-art"
        viewBox="0 0 640 360"
        preserveAspectRatio="xMidYMid meet"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id={`${id}-glass`} x1="0" y1="0" x2=".8" y2="1">
            <stop stopColor="var(--glass-top)" />
            <stop offset="1" stopColor="var(--glass-bottom)" />
          </linearGradient>
          <linearGradient id={`${id}-wood`} x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="var(--wood-top)" />
            <stop offset="1" stopColor="var(--wood-end)" />
          </linearGradient>
          <linearGradient id={`${id}-seat`} x1="0" y1="0" x2=".7" y2="1">
            <stop stopColor="var(--seat-top)" />
            <stop offset="1" stopColor="var(--seat-bottom)" />
          </linearGradient>
          <linearGradient id={`${id}-beam`} x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="var(--lamp)" stopOpacity=".02" />
            <stop offset="1" stopColor="var(--lamp)" stopOpacity=".45" />
          </linearGradient>
          <radialGradient id={`${id}-shadow`}>
            <stop stopColor="var(--shadow-ink)" stopOpacity=".3" />
            <stop offset="1" stopColor="var(--shadow-ink)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="320" cy="317" rx="258" ry="31" fill={`url(#${id}-shadow)`} />
        <path d="M72 270L430 236L568 285L207 335L72 285Z" fill="var(--floor-edge)" />
        <path d="M72 270L430 236L568 285L207 324Z" fill="var(--floor)" />
        <path d="M72 58L430 24L430 236L72 270Z" fill="var(--wall-front)" />
        <path d="M430 24L568 75L568 285L430 236Z" fill="var(--wall-side)" />
        <path d="M72 58L430 24L440 28L82 63Z" fill="var(--paper)" opacity=".8" />
        <path d="M430 24L440 28L440 239L430 236Z" fill="var(--wall-edge)" />
        <path
          d="M72 262L430 228L430 236L72 270Z M440 232L568 277L568 285L440 239Z"
          fill="var(--wall-edge)"
        />
        <g stroke="var(--floor-edge)" strokeWidth="1.2" opacity=".4">
          <path d="M115 286L470 251M160 307L517 268M206 324L568 285" />
          <path d="M210 258L345 309M325 247L460 297" />
        </g>
        <g transform="matrix(1 -.095 0 1 94 88)">
          <rect x="-5" y="-5" width="142" height="145" rx="1" fill="var(--window-shadow)" />
          <rect width="132" height="135" fill={`url(#${id}-glass)`} />
          <path
            d="M2 100L23 78L40 84L59 62L78 73L98 55L131 72V135H2Z"
            fill="var(--leaf-dark)"
            opacity=".21"
          />
          <path d="M9 4L52 4L9 66ZM68 4L110 4L68 66Z" fill="var(--paper)" opacity=".16" />
          <path
            d="M0 0H132V135H0ZM66 0V135M0 91H132"
            fill="none"
            stroke="var(--window-frame)"
            strokeWidth="5"
          />
          <path
            d="M4 7H128M4 14H128M4 21H128"
            stroke="var(--window-frame)"
            strokeWidth="2"
            opacity=".55"
          />
          <path d="M-7 137H138L146 145H-2Z" fill="var(--window-frame)" />
          <rect x="59" y="60" width="3" height="13" rx="1" fill="var(--metal)" />
        </g>
        <path
          className="art-daylight"
          d="M101 191L219 180L312 271L188 287L77 262Z"
          fill="var(--sun)"
        />
        <g transform="matrix(1 -.095 0 1 277 84)">
          <rect x="2" y="4" width="119" height="76" rx="2" fill="var(--shadow-ink)" opacity=".12" />
          <rect width="118" height="74" rx="2" fill="var(--window-frame)" />
          <rect x="4" y="4" width="110" height="65" fill="var(--board)" />
          <g stroke="var(--board-line)" fill="none" strokeWidth="1.6" opacity=".7">
            <rect x="14" y="15" width="24" height="15" rx="2" />
            <rect x="66" y="15" width="29" height="15" rx="2" />
            <path d="M38 22H66M26 30V44H80V30M18 54H47M57 54H95" />
          </g>
          <path d="M-2 74H121L125 79H2Z" fill="var(--metal)" />
          <path d="M80 73H91" stroke="var(--seat-bottom)" strokeWidth="3" />
          <path d="M96 73H107" stroke="var(--board-line)" strokeWidth="3" />
        </g>
        <g transform="matrix(1 .36 0 1 470 103)">
          <rect width="62" height="83" rx="3" fill="var(--floor-edge)" />
          <g stroke="var(--wall-edge)" strokeWidth="3" opacity=".65">
            <path d="M9 7V76M18 7V76M27 7V76M36 7V76M45 7V76M54 7V76" />
          </g>
        </g>
        <path d="M270 43V67M374 33V57" stroke="var(--metal)" strokeWidth="1.5" />
        <path d="M256 68L389 55L394 63L261 77Z" fill="var(--lamp-case)" />
        <path d="M261 77L394 63V67L261 81Z" fill="var(--lamp)" />
        <path
          className="art-lamplight"
          d="M261 81L394 67L454 261L181 286Z"
          fill={`url(#${id}-beam)`}
        />
        <path d="M141 269L404 242L490 282L227 314Z" fill="var(--rug)" />
        <path
          d="M154 271L402 246L476 281L229 309Z"
          fill="none"
          stroke="var(--rug-line)"
          strokeWidth="1.3"
        />
        {forum ? (
          <>
            {[204, 263, 322, 381].map((x, i) => (
              <Chair key={x} id={id} x={x} y={202 - i * 6} scale={0.75} />
            ))}
          </>
        ) : (
          <>
            <Chair id={id} x={218} y={208} scale={0.86} />
            <Chair id={id} x={355} y={193} scale={0.86} />
          </>
        )}
        <ellipse cx="307" cy="288" rx="131" ry="20" fill="var(--shadow-ink)" opacity=".12" />
        <path
          d="M218 254L214 292M371 238L376 283"
          stroke="var(--metal)"
          strokeWidth="7"
          strokeLinecap="round"
        />
        <path
          d="M209 292L225 293M367 283L384 284"
          stroke="var(--metal)"
          strokeWidth="4"
          strokeLinecap="round"
        />
        {forum ? (
          <>
            {' '}
            <path
              d="M168 235Q166 229 176 227L397 205Q408 204 411 209L446 244V254L206 281L168 245Z"
              fill="var(--wood-side)"
            />
            <path
              d="M168 234Q165 228 176 226L397 204Q407 203 411 209L446 244Q450 249 440 251L215 275Q207 276 202 272Z"
              fill={`url(#${id}-wood)`}
            />
            <path
              d="M184 235L403 213M199 247L416 225M213 260L431 239"
              stroke="var(--wood-side)"
              strokeWidth=".7"
              opacity=".23"
            />{' '}
          </>
        ) : (
          <>
            {' '}
            <ellipse
              cx="306"
              cy="248"
              rx="121"
              ry="37"
              transform="rotate(-6 306 248)"
              fill="var(--wood-side)"
            />
            <ellipse
              cx="306"
              cy="240"
              rx="121"
              ry="37"
              transform="rotate(-6 306 240)"
              fill={`url(#${id}-wood)`}
            />
            <path
              d="M207 240Q305 211 402 225M219 251Q309 226 403 238"
              stroke="var(--wood-side)"
              strokeWidth="1"
              opacity=".2"
            />{' '}
          </>
        )}
        <g transform="translate(271 219) rotate(-7)">
          <path d="M-17 0L17 0L23 22L-11 22Z" fill="var(--metal)" />
          <path d="M-14 3L14 3L18 18L-9 18Z" fill="var(--screen)" />
          <path d="M-11 22L23 22L33 29L-1 30Z" fill="var(--window-frame)" />
          <path d="M-5 24L21 24M1 27H25" stroke="var(--metal)" strokeWidth=".8" />
          <path d="M-9 5L-6 14L6 5Z" fill="var(--paper)" opacity=".12" />
        </g>
        <g transform="translate(325 235) rotate(-7)">
          <rect width="31" height="20" rx="1" fill="var(--book)" />
          <path d="M4 2V18M6 5H26M6 9H22" stroke="var(--paper)" strokeWidth=".8" opacity=".8" />
          <path d="M37 4H49V17H37Z" fill="var(--paper)" />
          <path d="M40 7H47M40 10H46" stroke="var(--board-line)" strokeWidth=".8" />
        </g>
        <g transform="translate(382 221)">
          <ellipse cy="8" rx="9" ry="3.2" fill="var(--shadow-ink)" opacity=".18" />
          <path d="M-6-3H6V6Q0 11-6 6Z" fill="var(--paper)" />
          <path d="M6-1Q14-1 11 5H6" fill="none" stroke="var(--paper)" strokeWidth="2" />
          <ellipse cy="-3" rx="6" ry="2" fill="var(--wood-side)" />
        </g>
        {forum ? (
          <>
            {[220, 281, 342, 403].map((x, i) => (
              <Chair key={x} id={id} x={x} y={282 - i * 6} scale={0.75} />
            ))}
          </>
        ) : (
          <>
            <Chair id={id} x={259} y={282} scale={0.94} />
            <Chair id={id} x={397} y={267} scale={0.94} />
          </>
        )}
        <g transform="translate(518 267)">
          <ellipse cx="3" cy="30" rx="26" ry="8" fill="var(--shadow-ink)" opacity=".15" />
          <path d="M-20-4L-15 25Q0 36 16 25L21-4Z" fill="var(--pot)" />
          <path d="M0-4H21L16 25Q8 32 0 31Z" fill="var(--pot-dark)" opacity=".6" />
          <ellipse cy="-4" rx="21" ry="7" fill="var(--pot-dark)" />
          <path
            d="M0-3L-1-80M0-29L-23-54M0-42L25-68M-1-63L-15-84"
            stroke="var(--leaf-dark)"
            strokeWidth="3"
            fill="none"
          />
          <path
            d="M0-51Q-34-45-30-77Q-4-77 0-51M0-28Q-31-18-34-49Q-10-57 0-28M0-68Q-18-80-10-107Q12-99 0-68"
            fill="var(--leaf-dark)"
          />
          <path
            d="M0-42Q35-38 34-70Q8-72 0-42M0-66Q27-65 24-94Q2-91 0-66M0-15Q28-12 29-39Q9-46 0-15"
            fill="var(--leaf)"
          />
          <path
            d="M4-46L27-64M4-70L19-87M4-20L23-33"
            stroke="var(--paper)"
            strokeWidth="1"
            opacity=".2"
          />
        </g>
      </svg>
    </div>
  );
}
