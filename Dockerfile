FROM python:3.13

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY uv.lock /opt/temportofoto/uv.lock
COPY pyproject.toml /opt/temportofoto/pyproject.toml

WORKDIR /opt/temportofoto
RUN uv sync --frozen --no-cache --no-dev

COPY app /opt/temportofoto/app

CMD ["/opt/temportofoto/.venv/bin/fastapi", "run", "app/main.py", "--port", "8000", "--host", "0.0.0.0"]
