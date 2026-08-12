FROM python:3.12-slim

WORKDIR /srv

# CBC solver (needed by PuLP for optimise.py's ILP) + build tools for lightgbm/scipy wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ /srv/scripts/
COPY backend/app/ /srv/app/
COPY data/ /srv/data/

# Docker seeds a named volume from the image's existing directory contents on
# first container creation -- so baking the current fpl_cache.db in here means
# a fresh deploy starts with real historical data, not an empty DB. After
# that first run, the volume mount takes over and persists independently.
VOLUME ["/srv/data"]
ENV PYTHONUNBUFFERED=1
ENV FPL_PROJECT_ROOT=/srv

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
