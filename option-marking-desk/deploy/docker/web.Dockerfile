# Build from the repo root:  docker build -f deploy/docker/web.Dockerfile -t omd-web:dev .
# Assumes the frontend lives in web/ (Vite -> web/dist).
FROM node:22-alpine AS build
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
