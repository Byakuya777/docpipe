FROM node:24-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

# Dev server for local work, matching the backend's --reload. M5 adds a
# production build stage for the real deploy.
CMD ["npx", "next", "dev", "-H", "0.0.0.0", "-p", "3000"]
