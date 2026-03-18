FROM python:3.11-slim

# Create a non-root user
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create logs dir and hand ownership to botuser
RUN mkdir -p logs && chown -R botuser:botuser /app

USER botuser

# Persist logs outside the container
VOLUME ["/app/logs"]

# Expose Streamlit port
EXPOSE 8501

# Default: launch Streamlit UI
# Override with CLI args to use the CLI instead:
#   docker run ... --entrypoint python <image> cli.py --symbol BTCUSDT ...
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]