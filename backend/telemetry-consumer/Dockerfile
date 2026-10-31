FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# No EXPOSE: this is a background worker with no HTTP server.
CMD ["python", "main.py"]
