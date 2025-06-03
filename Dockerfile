FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Copy & install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Install Playwright browsers
#    The command below will install Chromium, Firefox, and WebKit
RUN playwright install --with-deps

# 3) Copy your bot code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# Create subtitle cache dir
RUN mkdir -p /app/subtitles_cache

# Expose 8080 if you’re using health‐check server
EXPOSE 8080

CMD ["python", "bot.py"]
