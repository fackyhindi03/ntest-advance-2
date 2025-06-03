# Dockerfile

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy & install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# Create subtitle cache (optional; bot will also create at runtime if missing)
RUN mkdir -p /app/subtitles_cache

# Expose port 8080 if you're running a health check server.
# (If you deploy as a Worker, you can omit EXPOSE entirely.)
EXPOSE 8080

CMD ["python", "bot.py"]
