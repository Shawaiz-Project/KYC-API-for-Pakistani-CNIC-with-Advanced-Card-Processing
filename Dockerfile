FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY Requirements.txt ./Requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r Requirements.txt
COPY ["Django Api", "/app/Django Api"]
WORKDIR "/app/Django Api"
RUN python manage.py collectstatic --noinput
RUN mkdir -p /data/private-objects /app/var/static && chown -R 10001:10001 /data /app/var
USER 10001
CMD ["gunicorn", "api.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "300", "--access-logfile", "-"]
