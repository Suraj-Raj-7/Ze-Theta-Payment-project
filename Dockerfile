# Dockerfile
# Packages the FastAPI application into a runnable container.
# PostgreSQL runs as a SEPARATE container (official postgres:15
# image) - docker-compose.yml wires them together over a network.

FROM python:3.13-slim

WORKDIR /app

# Install dependencies first (separate layer) so Docker can cache
# this step - rebuilds are much faster when only code changes,
# not dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the actual application code
COPY . .

EXPOSE 8000

# Runs migrations automatically on startup, THEN starts the server.
# This is what makes `docker-compose up` fully self-contained -
# no manual "remember to run alembic upgrade head" step needed.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]