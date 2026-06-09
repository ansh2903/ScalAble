FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
COPY setup.py .
COPY spore ./spore
COPY frontend ./frontend
COPY docker ./docker

RUN apt-get update && apt-get install -y --no-install-recommends \
    unixodbc \
    unixodbc-dev \
    libpq-dev \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV APP_HOST=0.0.0.0
ENV FLASK_ENV=development

EXPOSE 5000

CMD ["python3", "-m", "spore._app"]
