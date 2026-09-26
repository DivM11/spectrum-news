FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml README.md ./
COPY src/ src/
COPY app.py .env.example ./
COPY data/ data/
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev
EXPOSE 8501
CMD ["uv", "run", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
