FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate gRPC stubs from .proto (package-aware imports)
RUN python -m grpc_service.generate_stubs

EXPOSE 8000 50051

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "myprojects.asgi:application"]
