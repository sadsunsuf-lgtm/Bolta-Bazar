# Use Python 3.9 for maximum compatibility with Firebase/Firestore libraries
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8080

# Set working directory
WORKDIR /app

# Install essential system dependencies for audio processing and C-extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run the application using 'exec' to ensure signals are handled correctly by Cloud Run
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT