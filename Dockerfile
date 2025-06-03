# Use an official Python runtime as a parent image.
# You can choose 3.9, 3.10, 3.11, etc. 3.10-slim is a good balance.
FROM python:3.10-slim

# ---- 1) Set environment variables ----
# Prevent Python from writing .pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure Python output is sent straight to the terminal (no buffering)
ENV PYTHONUNBUFFERED=1

# ---- 2) Create a working directory ----
WORKDIR /app

# ---- 3) Copy requirements.txt and install dependencies ----
# Copy requirements.txt first to leverage Docker layer caching.
COPY requirements.txt .

# Install required Python packages
RUN pip install --no‐cache‐dir -r requirements.txt

# ---- 4) Copy the rest of your source code ----
COPY bot.py .
COPY hianimez_scraper.py .
COPY utils.py .

# If you have a subtitles_cache folder in your .gitignore, we don't need to copy it.
# The bot will create it at runtime if necessary.

# ---- 5) Set the default command to run the bot ----
# You must supply your TELEGRAM_TOKEN via an environment variable when you deploy.
# (Alternatively, you can hard‐code it in bot.py, but ENV is more secure.)
CMD ["python", "bot.py"]
