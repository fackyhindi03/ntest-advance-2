FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Copy & install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Install Playwright browsers + dependencies
RUN playwright install --with-deps

# 3) Copy your source code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# 4) Create subtitle cache dir
RUN mkdir -p /app/subtitles_cache

# Expose port 8080 for both Koyeb health-check and Telegram webhook
EXPOSE 8080

# 5) Run the bot (which now starts Flask on port 8080)
CMD ["python", "bot.py"]
