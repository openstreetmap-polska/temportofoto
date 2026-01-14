FROM python:3.13-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY uv.lock /uv.lock
COPY pyproject.toml /pyproject.toml
COPY app /app

# Install the application dependencies.
RUN uv sync --frozen --no-cache --no-dev

# Run the application.
CMD ["uv", "run", "fastapi", "run", "app/main.py", "--port", "80", "--host", "0.0.0.0"]
