FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the SQLite file outside the image layer if your host supports a
# mounted volume at /app/data (recommended) -- otherwise it lives in the
# container and is lost on redeploy.
ENV DB_PATH=/app/weeklies.db

EXPOSE 8080
CMD ["python", "run.py"]
