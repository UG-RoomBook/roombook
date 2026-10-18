import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const archive = readFileSync(
  resolve(process.cwd(), '../docs/design/baselines/v1/approved-prototype.html'),
  'utf8',
);
const illustration = readFileSync(
  resolve(process.cwd(), 'src/shared/illustrations/RoomIllustration.tsx'),
  'utf8',
);
const materials = readFileSync(
  resolve(process.cwd(), 'src/shared/illustrations/room-illustration.css'),
  'utf8',
);

function svgNodeAttributes(source: string) {
  const htmlAttributes = source
    .replace(/=\{`([^`]*)`\}/g, '="$1"')
    .replace(/className=/g, 'class=')
    .replace(/strokeWidth=/g, 'stroke-width=')
    .replace(/strokeLinecap=/g, 'stroke-linecap=')
    .replace(/stopColor=/g, 'stop-color=')
    .replace(/stopOpacity=/g, 'stop-opacity=');
  return [
    ...htmlAttributes.matchAll(
      /<(path|ellipse|rect|g|linearGradient|radialGradient|stop)\b([^>]+)>/g,
    ),
  ].map((node) => ({
    tag: node[1],
    attributes: [...(node[2] ?? '').matchAll(/([:\w-]+)="([^"]*)"/g)].map((attribute) => [
      attribute[1],
      attribute[2],
    ]),
  }));
}

describe('v1 illustration preservation', () => {
  it('retains every archived SVG shape, gradient and attribute', () => {
    const archivedSvg = archive
      .split('const chair=(x,y,scale=1)=>`')[1]
      ?.split('function renderRooms()')[0];
    expect(archivedSvg).toBeDefined();
    const expected = svgNodeAttributes(archivedSvg ?? '');
    expect(expected).toHaveLength(99);
    expect(svgNodeAttributes(illustration)).toEqual(expected);
  });

  it('retains the approved theme material values and SVG motion rules', () => {
    const approvedMaterials = archive.split('\n').slice(72, 85).join('\n');
    const normalized = (value: string) =>
      value
        .replace(/(^|[^a-zA-Z0-9_-])0\.(\d+)/g, '$1.$2')
        .replace(/\s/g, '')
        .replace(/;}/g, '}');
    expect(normalized(materials)).toBe(normalized(approvedMaterials));
  });
});
