FROM python:3.9-slim

WORKDIR /app

# Install system dependencies (needed for some Python libraries)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Start uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5050"]