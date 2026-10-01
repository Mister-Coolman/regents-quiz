FROM python:3.11-slim AS base

# System deps (no recommends = smaller). Everything in requirements.txt is
# pure Python, so no compiler, image or OCR libraries: those belonged to the
# offline extraction pipeline in scripts/, which never runs in this image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

# Print straight to the log: without this, Python buffers stdout when it isn't
# a terminal and the app's log lines (llm_call cost lines included) only
# reach `fly logs` in late batches, or never if the machine stops.
ENV PYTHONUNBUFFERED=1

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
# Copy only the modules. `COPY . .` here used to re-copy static/ and the
# local venv/ into this layer, so every code deploy re-pushed ~200 MB and
# the cached layers above saved nothing.
COPY *.py ./

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
