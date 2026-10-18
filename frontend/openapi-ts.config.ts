import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: './openapi/roombook.json',
  output: 'src/shared/api/generated',
  plugins: ['@hey-api/typescript', '@hey-api/client-fetch', '@hey-api/sdk'],
});
