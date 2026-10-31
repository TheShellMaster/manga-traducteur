FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    unrar-free p7zip-full fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY web/ ./web/
COPY server.py ./server.py
RUN mkdir -p /app/data
ENV MTS_HOME=/app/data
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
