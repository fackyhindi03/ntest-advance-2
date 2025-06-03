# 1) Start from an official slim‐Python base image
FROM python:3.10-slim

# 2) Prevent Python from writing .pyc files and force unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3) Create and switch to /app
WORKDIR /app

# 4) Copy requirements.txt first (to leverage Docker’s layer cache)
COPY requirements.txt .

# 5) Install Python dependencies using ASCII hyphens
RUN pip install --no-cache-dir -r requirements.txt

# 6) Copy the rest of your application code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# 7) Ensure the subtitles_cache directory will exist at runtime
RUN mkdir -p /app/subtitles_cache

# 8) Tell Docker how to run your bot
CMD ["python", "bot.py"]
