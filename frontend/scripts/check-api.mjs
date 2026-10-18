import { createHash } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';

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

// Generate outside the checkout so a failed drift check cannot change source files.
const temporary = await mkdtemp(join(tmpdir(), 'roombook-api-check-'));
const packageRoot = join(root, 'node_modules/@hey-api/openapi-ts');
const metadata = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
const bin = typeof metadata.bin === 'string' ? metadata.bin : metadata.bin['openapi-ts'];
let exitCode = 0;
try {
  const generation = spawnSync(
    process.execPath,
    [join(packageRoot, bin), '--output', temporary, '--no-log-file'],
    { cwd: root, stdio: 'inherit' },
  );
  if (generation.status !== 0) {
    exitCode = generation.status ?? 1;
  } else {
    const actual = await snapshot(generated);
    const expected = await snapshot(temporary);
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      console.error('Generated API files differ from backend/openapi.json.');
      console.error('Run npm run api:generate, then review and commit the generated changes.');
      exitCode = 1;
    } else {
      console.log('Generated API files match backend/openapi.json.');
    }
  }
} finally {
  await rm(temporary, { recursive: true, force: true });
}
process.exitCode = exitCode;
