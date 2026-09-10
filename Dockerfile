# CNC Finance — single image: Telegram bot + dashboard API + static dashboard.
# Uses a Debian base so WeasyPrint's native Pango/Cairo/GDK-Pixbuf libraries
# are available (the recurring pain point on buildpack/Nixpacks builds).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      libgdk-pixbuf-2.0-0 \
      libcairo2 \
      libffi-dev \
      libharfbuzz0b \
      shared-mime-info \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
