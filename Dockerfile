FROM python:3.12-slim

# Install system dependencies (unrar / 7z and fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    unrar-free \
    p7zip-full \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install lightweight python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ ./app/
COPY main.py .

# Create input and output mount points
RUN mkdir -p /app/input /app/output

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
