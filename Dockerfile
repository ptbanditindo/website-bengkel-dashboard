FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install Python dependencies (no system compiler needed)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application packages and entry point
COPY ai ./ai
COPY bot ./bot
COPY database ./database
COPY repositories ./repositories
COPY services ./services
COPY api ./api
COPY migrations ./migrations
COPY alembic.ini .
COPY main.py .

# Create a non-root user and a persistent data directory
RUN useradd -m -u 1000 botuser && \
    mkdir -p /app/data && \
    chown -R botuser:botuser /app

USER botuser

# Apply migrations (via init_db) then start the bot
CMD ["python", "main.py"]
