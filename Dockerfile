FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

FROM base AS runtime

CMD ["python", "-u", "bot.py"]

FROM base AS test

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
RUN mkdir -p /app/data/ciphers

CMD ["python", "-m", "pytest", "-q"]
