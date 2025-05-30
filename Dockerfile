FROM python:3.13-slim

WORKDIR /app

VOLUME /data
ENV CACHE_DIR=/data

# Install main dependencies
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Copy application files
COPY opus_sync.py entrypoint.sh run_tests.py ./
RUN chmod +x entrypoint.sh run_tests.py

# Copy test files
COPY tests/ ./tests/

ENTRYPOINT ["./entrypoint.sh"]
