FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml MANIFEST.in demo.py ./
COPY pedestrian_nav ./pedestrian_nav

RUN pip install --no-cache-dir .

EXPOSE 8501 5001

ENV OSRM_URL="http://osrm:5000"

CMD ["streamlit", "run", "demo.py", "--server.address=0.0.0.0", "--server.port=8501"]