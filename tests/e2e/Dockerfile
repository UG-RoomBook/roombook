# Browser-test runner used on the Test server. Built once and cached there,
# so each pipeline run only copies the specs in.
FROM node:24.19.0-bookworm@sha256:4196d66a565c6f195728d9952f161f4adfe2ad753052a08b7ec7f1c5a6bda42b
WORKDIR /e2e
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund \
 && npx playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY playwright.config.ts ./
COPY specs ./specs
ENTRYPOINT ["npx", "playwright", "test"]
