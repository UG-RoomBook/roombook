import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const generated = join(root, 'src/shared/api/generated');

async function snapshot(folder, prefix = '') {
  const files = {};
  for (const entry of await readdir(folder, { withFileTypes: true })) {
    const relative = prefix + entry.name;
    if (entry.isDirectory())
      Object.assign(files, await snapshot(join(folder, entry.name), relative + '/'));
    else
      files[relative] = createHash('sha256')
        .update(await readFile(join(folder, entry.name)))
        .digest('hex');
  }
  return Object.fromEntries(
    Object.entries(files).sort(([left], [right]) => left.localeCompare(right)),
  );
}

const before = await snapshot(generated);
const packageRoot = join(root, 'node_modules/@hey-api/openapi-ts');
const metadata = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
const bin = typeof metadata.bin === 'string' ? metadata.bin : metadata.bin['openapi-ts'];
const generation = spawnSync(process.execPath, [join(packageRoot, bin)], {
  cwd: root,
  stdio: 'inherit',
});
if (generation.status !== 0) process.exit(generation.status ?? 1);
const after = await snapshot(generated);
if (JSON.stringify(before) !== JSON.stringify(after)) {
  console.error('Generated API files changed. Review and commit the regenerated client.');
  process.exit(1);
}
console.log('Generated API files match the checked contract.');
