# Ensure Python is available (example base image)
FROM python:3.11-slim

# Create and activate venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install requirements
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the app files
COPY . /app
WORKDIR /app

# Run the bot
CMD ["python", "bot.py"]
