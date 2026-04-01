FROM python:3.12-slim

WORKDIR /app

# System deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create dirs for data persistence
RUN mkdir -p uploads

EXPOSE ${PORT:-5000}

CMD gunicorn webapp:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120
