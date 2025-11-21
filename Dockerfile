FROM continuumio/miniconda3

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install -y \
    unixodbc \
    unixodbc-dev \
    libpq-dev \
    curl \
    iproute2 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN conda create -n scalable python=3.12 -y

SHELL ["conda", "run", "-n", "scalable", "/bin/bash", "-c"]

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=development

EXPOSE 5000

CMD ["conda", "run", "--no-capture-output", "-n", "scalable", "python", "-m", "src.app"]
