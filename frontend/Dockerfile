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
# The rewrite destination in next.config.ts is resolved during `next build` and
# baked into .next/routes-manifest.json — it is NOT re-read per request. So
# API_URL must be present at BUILD time, not just at runtime, or the deployed
# app proxies to localhost and every /api/* call fails with ECONNREFUSED.
# `next dev` does re-evaluate the config at startup, which is why compose hides
# this: only the production build is affected.
# Railway injects service variables into a Dockerfile build only for names
# declared with ARG, in the stage that needs them.
ARG API_URL
ENV API_URL=$API_URL
COPY . .
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
