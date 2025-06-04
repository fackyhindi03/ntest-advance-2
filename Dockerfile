# Dockerfile for your “Hianime Telegram Bot” repository

FROM python:3.10-slim

# 1) Install OS‐level dependencies (ffmpeg for HLS→MP4 conversion, plus build libaries for lxml, etc.)
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

# 2) Prevent .pyc files and force unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3) Set working directory
WORKDIR /app

# 4) Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5) Copy application code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# 6) Create cache folders for subtitles and videos
RUN mkdir -p /app/subtitles_cache /app/videos_cache

# 7) Expose port 8080 (Flask health check + webhook)
EXPOSE 8080

# 8) Start the bot
CMD ["python", "bot.py"]
