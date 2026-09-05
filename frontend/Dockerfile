# syntax=docker/dockerfile:1

FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Local development: hot-reloading dev server. docker-compose builds this stage
# explicitly (`target: dev`) and bind-mounts src over it.
FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["npx", "next", "dev", "-H", "0.0.0.0", "-p", "3000"]

FROM deps AS build
COPY . .
# API_URL is read per request by the rewrite in next.config.ts, not inlined at
# build time, so the build needs no reachable backend.
RUN npm run build

# Production: the default (last) stage, which is what Railway builds.
FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/next.config.ts ./
EXPOSE 3000
# Railway injects PORT and routes public traffic to it; the fallback keeps the
# image runnable on its own. Only the public proxy talks to this service, so
# 0.0.0.0 is enough — unlike the backend, nothing reaches it privately.
CMD ["sh", "-c", "npx next start -H 0.0.0.0 -p ${PORT:-3000}"]
