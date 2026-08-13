FROM python:3.11-slim AS base

# System deps (no recommends = smaller)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    libgl1 libglib2.0-0 libjpeg-dev \
    tesseract-ocr \
    curl ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

# Create app dir & user
WORKDIR /app
RUN useradd -m -u 10001 appuser

# Copy just requirements first for better caching
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn

# Question images (~148 MB) change only when the extraction pipeline is re-run,
# so give them their own layer BEFORE the app code. A code-only deploy then
# reuses this cached layer instead of rebuilding and re-pushing 148 MB.
COPY static/ ./static/

# Question database -- changes when explanations are regenerated, which is
# far less often than code, so it also gets its own layer.
COPY regentsqs.db ./

# Application code last: this is what actually changes between deploys.
COPY . .

# (Optional) If you serve any static assets, ensure readable perms
RUN chown -R appuser:appuser /app

# Expose Flask/Gunicorn port
EXPOSE 8080

# Use tini as PID 1 for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Run gunicorn; workers/threads are conservative—tune if needed
CMD ["gunicorn","app:app", \
     "-w","1","-k","gthread","--threads","8", \
     "-b","[::]:8080", \
     "--timeout","120","--graceful-timeout","30","--preload", \
     "--log-level","info","--access-logfile","-"]

USER appuser
