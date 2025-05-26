FROM python:3.13-slim

WORKDIR /app

VOLUME /data
ENV CACHE_DIR=/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY opus_sync.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]