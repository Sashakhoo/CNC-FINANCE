# Public entry for main.codencode.my (launcher) and crm.codencode.my (CRM):
# serves the built React app and proxies /api to the backend.
FROM node:22-slim AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
ENV PORT=80 BACKEND_URL=http://backend:8000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
