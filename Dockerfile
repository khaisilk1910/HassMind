FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    UMASK=077 \
    TZ=Asia/Ho_Chi_Minh \
    TIMEZONE=Asia/Ho_Chi_Minh

WORKDIR /app

# System tzdata is required so libc/coreutils (for example `date`) and Python
# resolve the same IANA timezone supplied through TZ/TIMEZONE.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 hassmind

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY config /app/config
COPY static /app/static
COPY VERSION /app/VERSION

RUN mkdir -p /data /data/secrets /data/skills /knowledge /tmp && chown -R hassmind:hassmind /app /data /knowledge /tmp && chmod 700 /data/secrets /data/skills

USER hassmind
EXPOSE 8090

CMD ["python", "-m", "app.main"]
