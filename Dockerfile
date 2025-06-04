# Dockerfile

FROM python:3.10-slim

# 1) System dependencies (ffmpeg + build tools for lxml, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      build-essential \
      libxml2-dev \
      libxslt1-dev \
      ca-certificates \
      curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 2) Prevent .pyc files, unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3) Working directory
WORKDIR /app

# 4) Copy & install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5) Copy application code
COPY .env .
COPY bot.py .
COPY utils.py .
COPY hianimez_scraper.py .

# 6) Create cache directories
RUN mkdir -p /app/subtitles_cache /app/videos_cache

# 7) Expose port 8080 for Flask
EXPOSE 8080

# 8) Entrypoint
CMD ["python", "bot.py"]
