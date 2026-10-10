FROM python:3.12-slim

WORKDIR /app

# Set environment variables (PORT defaults to 8080, but can be dynamically overridden by Render/Cloud platforms)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BLAST_HOST=0.0.0.0 \
    PORT=8080

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .
RUN pip install --no-cache-dir -e .

# Expose Blast gateway ports
EXPOSE 8080
EXPOSE 8000

# Health check dynamically checks the active PORT
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD sh -c "curl -f http://localhost:\${PORT:-8080}/health || exit 1"

# Default execution entrypoint
CMD ["python3", "main.py"]
