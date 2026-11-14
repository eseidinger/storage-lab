FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_URL=/api
ARG VITE_OIDC_AUTHORITY
ARG VITE_OIDC_CLIENT_ID=storage-lab-portal
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_LAB_UI_DIST=/app/frontend
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --no-create-home --uid 10001 storage-lab
COPY backend/src/ ./src/
COPY --from=frontend-build /build/frontend/dist/ ./frontend/
USER storage-lab
EXPOSE 8000
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "storage_lab.api:app", "--host", "127.0.0.1", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
