# Dockerfile

FROM python:3.10-slim

# 1) Install CA certs for HTTPS + Playwright deps
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
      libxdamage1 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 2) Python settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 3) Copy & install pip packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4) Install Playwright browsers + system deps
RUN playwright install --with-deps

# 5) Copy application code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# 6) Create subtitle cache folder
RUN mkdir -p /app/subtitles_cache

# 7) Expose port 8080 for health check + webhook
EXPOSE 8080

# 8) Start the bot
CMD ["python", "bot.py"]
