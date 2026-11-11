FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apache2 \
        apache2-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mod_wsgi-express module-config > /etc/apache2/conf-available/wsgi.conf \
    && a2enconf wsgi

COPY web_service.py web_service.wsgi /app/

COPY apache-vhost.conf /etc/apache2/sites-available/000-default.conf

RUN mkdir -p /app/uploads /var/run/apache2 /var/lock/apache2 \
    && chown -R www-data:www-data /app/uploads /var/run/apache2 /var/lock/apache2 \
    && chmod 644 /app/web_service.wsgi

EXPOSE 80

RUN ln -sf /dev/stdout /var/log/apache2/access.log \
    && ln -sf /dev/stderr /var/log/apache2/error.log

CMD ["apache2ctl", "-D", "FOREGROUND"]
