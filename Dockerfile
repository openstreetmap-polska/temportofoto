FROM python:3.13

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY uv.lock /opt/temportofoto/uv.lock
COPY pyproject.toml /opt/temportofoto/pyproject.toml
COPY app /opt/temportofoto/app

# Install the application dependencies.
WORKDIR /opt/temportofoto
RUN uv sync --frozen --no-cache --no-dev

# Run the application.
CMD ["/opt/temportofoto/.venv/bin/fastapi", "run", "app/main.py", "--port", "80", "--host", "0.0.0.0"]
