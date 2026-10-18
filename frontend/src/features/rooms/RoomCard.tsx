import { ArrowUpRight, DoorOpen, Users } from 'lucide-react';
import type { Room, SearchFilters } from '@/shared/api/types';
import { RoomIllustration, roomVisualDetails } from '@/shared/illustrations';
import { Button } from '@/shared/ui';

type RoomCardProps = {
  room: Room;
  filters: SearchFilters;
  hasInterval: boolean;
  onBook: (room: Room) => void;
};

export function RoomCard({ room, filters, hasInterval, onBook }: RoomCardProps) {
  const canBook = hasInterval && room.active && room.available === true;
  const status = !room.active
    ? 'Inactive'
    : !hasInterval
      ? 'Choose a time'
      : room.available === true
        ? 'Available'
        : room.available === false
          ? 'Booked'
          : 'Availability not reported';

  return (
    <article className="sw-room" aria-label={room.name}>
      <RoomIllustration room={room} />
      <div className="sw-room-info">
        <div className="sw-room-heading">
          <h3>{room.name}</h3>
          <span className={`sw-status ${canBook ? '' : 'busy'}`.trim()}>{status}</span>
        </div>
        <p className="sw-small">{room.location}</p>
        <div className="sw-facts">
          <span>
            <Users size={18} aria-hidden="true" />
            {room.capacity} people
          </span>
          <span>
            <DoorOpen size={18} aria-hidden="true" />
            {roomVisualDetails(room).kind}
          </span>
        </div>
        <div className="sw-room-bottom">
          <div>
            <small>SELECTED TIME</small>
            <strong>{hasInterval ? `${filters.start}–${filters.end}` : 'Not selected'}</strong>
          </div>
          <Button
            variant={canBook ? 'primary' : 'secondary'}
            disabled={!canBook}
            onClick={() => onBook(room)}
            aria-label={canBook ? `Book ${room.name}` : `${room.name}: ${status.toLowerCase()}`}
          >
            {hasInterval && !canBook ? 'Unavailable' : 'Book room'}
            <ArrowUpRight size={18} aria-hidden="true" />
          </Button>
        </div>
      </div>
    </article>
  );
}
