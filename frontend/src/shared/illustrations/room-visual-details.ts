import type { Room } from '@/shared/api/types';

export type IllustratedRoom = Pick<Room, 'id' | 'name' | 'capacity'>;

export function roomVisualDetails(room: IllustratedRoom) {
  const knownForum = /^(?:the )?forum$/i.test(room.name);
  const knownStudio = /^(?:the )?studio$/i.test(room.name);
  const forum = knownForum || (!knownStudio && (/forum/i.test(room.id) || room.capacity > 4));
  const known = knownForum || knownStudio;
  return {
    forum,
    code: known ? (forum ? 'N.02' : 'W.01') : '',
    kind: known ? (forum ? 'Team space' : 'Small group') : 'Study room',
  };
}
