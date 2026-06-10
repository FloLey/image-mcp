FROM python:3.11-slim

WORKDIR /app

# Dependencies first for layer caching. pyproject.toml is the source of truth;
# the explicit pin here keeps the image build self-contained.
RUN pip install --no-cache-dir "fastmcp>=2.0,<3" "google-genai>=1.0" "pillow>=10"

COPY src/ ./src/

ENV IMG_ROOT=/srv/images
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8766

CMD ["python", "-m", "image_mcp.server"]
