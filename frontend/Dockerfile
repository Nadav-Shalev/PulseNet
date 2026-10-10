# syntax=docker/dockerfile:1
# The PulseNet web app: the production build, served by nginx, which also proxies
# /api and /uploads to the backend container (frontend/nginx.conf), the same
# layout as on the EC2. Built from this folder:
#   docker build -t pulsenet-frontend frontend

# Debian (glibc) and npm 10, like CI: the lockfile is made with npm 10.
FROM node:22-slim AS build
WORKDIR /app
# Cypress is a dev dependency; its 200 MB binary is not needed for a build.
ENV CYPRESS_INSTALL_BINARY=0
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# .env.production sets VITE_API_BASE_URL=/api: same origin as the page.
RUN npm run build

FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
