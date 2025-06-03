# Dockerfile

FROM python:3.10-slim

# 1) Ensure OS packages needed for HTTPS and Playwright are installed
RUN apt-get update && \
    apt-get install -y \
      ca-certificates \
      curl \
      libnss3 \
      libatk1.0-0 \
      libsdl2-2.0-0 \
      libxrandr2 \
      libgbm1 \
      libgtk-3-0 \
      libasound2 \
      libxcomposite1 \
      libx11-xcb1 \
      libxdamage1 \
      && apt-get clean && rm -rf /var/lib/apt/lists/*

# 2) Prevent Python from writing .pyc files and enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 3) Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4) Download Playwright browsers (Chromium/Firefox/WebKit) plus system deps
RUN playwright install --with-deps

# 5) Copy application code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# 6) Create subtitle cache directory
RUN mkdir -p /app/subtitles_cache

# 7) Expose port 8080 for both Koyeb health‐check and Telegram webhook
EXPOSE 8080

# 8) Default command
CMD ["python", "bot.py"]
