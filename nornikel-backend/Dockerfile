FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY run.py ./
COPY configs ./configs
COPY src ./src

RUN pip install --no-cache-dir .

ENV PYTHONPATH=src
ENV API_RELOAD=false

EXPOSE 8000

CMD ["python", "run.py"]
