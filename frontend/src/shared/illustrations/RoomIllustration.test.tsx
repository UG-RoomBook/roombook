import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RoomIllustration } from './RoomIllustration';

const studio = { id: 'studio', name: 'The Studio', capacity: 4 };
const forum = { id: 'forum', name: 'The Forum', capacity: 8 };

describe('approved room illustrations', () => {
  it('keeps all SVG definitions isolated when a room appears twice', () => {
    const { container } = render(
      <>
        <RoomIllustration room={studio} />
        <RoomIllustration room={studio} />
      </>,
    );
    const ids = [...container.querySelectorAll('svg [id]')].map((element) => element.id);
    expect(ids).toHaveLength(10);
    expect(new Set(ids).size).toBe(ids.length);
    for (const svg of container.querySelectorAll('svg')) {
      const localIds = new Set([...svg.querySelectorAll('[id]')].map((element) => element.id));
      for (const element of svg.querySelectorAll('[fill^="url(#"]')) {
        const target = element.getAttribute('fill')?.slice(5, -1);
        expect(localIds.has(target ?? '')).toBe(true);
      }
      expect(svg.getAttribute('viewBox')).toBe('0 0 640 360');
      expect(svg.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet');
    }
  });

  it('retains four Studio chairs and eight Forum chairs with separate material variants', () => {
    const { container } = render(
      <>
        <RoomIllustration room={studio} />
        <RoomIllustration room={forum} />
      </>,
    );
    const illustrations = container.querySelectorAll('.sw-visual');
    expect(illustrations[0]).not.toHaveClass('alt');
    expect(illustrations[1]).toHaveClass('alt');
    const chairCount = (element: Element) =>
      [...element.querySelectorAll('g[transform]')].filter((group) =>
        group.getAttribute('transform')?.includes(' scale('),
      ).length;
    expect(chairCount(illustrations[0]!)).toBe(4);
    expect(chairCount(illustrations[1]!)).toBe(8);
    expect(illustrations[0]).toHaveAttribute('aria-hidden', 'true');
  });
});
