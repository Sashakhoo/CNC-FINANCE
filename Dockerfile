# CNC Finance — single image: Telegram bot + dashboard API + static dashboard.
# Uses a Debian base so WeasyPrint's native Pango/Cairo/GDK-Pixbuf libraries
# are available (the recurring pain point on buildpack/Nixpacks builds).
FROM python:3.12-slim

# Full runtime dependency set for WeasyPrint (Pango / Cairo / GLib / HarfBuzz
# / Fontconfig). libglib2.0-0 (libgobject) and libharfbuzz-subset0 are the
# ones most often missing — WeasyPrint dlopen()s them via ctypes at render
# time, so a missing one is a runtime crash, not a build error.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      libpangoft2-1.0-0 \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
      libglib2.0-0 \
      libharfbuzz0b \
      libharfbuzz-subset0 \
      libfontconfig1 \
      libffi8 \
      shared-mime-info \
      fonts-dejavu \
      fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
# --proxy-headers + this env so request.url.scheme / X-Forwarded-Proto is
# trusted behind Railway's TLS edge (needed for the Secure cookie + HSTS).
# Set via env, not a CLI flag, to avoid shell-quoting the "*".
ENV FORWARDED_ALLOW_IPS="*"
EXPOSE 8000
# No `cd` here — WORKDIR already points at /app/backend. `sh -c` only so
# ${PORT} expands.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
