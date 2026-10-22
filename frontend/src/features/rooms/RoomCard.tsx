import { ArrowUpRight, DoorOpen, Users } from 'lucide-react';
import type { Room } from '@/shared/api/types';
import { RoomIllustration, roomVisualDetails } from '@/shared/illustrations';
import { Button } from '@/shared/ui';

export function RoomCard({ room, onChooseTime }: { room: Room; onChooseTime: () => void }) {
  return (
    <article className="sw-room" aria-label={room.name}>
      <RoomIllustration room={room} />
      <div className="sw-room-info">
        <div className="sw-room-heading">
          <h3>{room.name}</h3>
          {!room.active && <span className="sw-status busy">Inactive</span>}
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
          <span className="sw-small">
            {room.active ? 'View times for this room' : 'Currently unavailable'}
          </span>
          <Button
            variant={room.active ? 'primary' : 'secondary'}
            disabled={!room.active}
            onClick={onChooseTime}
            aria-label={room.active ? `Choose time for ${room.name}` : `${room.name}: inactive`}
          >
            {room.active ? 'Choose time' : 'Unavailable'}
            <ArrowUpRight size={18} aria-hidden="true" />
          </Button>
        </div>
      </div>
    </article>
  );
}
