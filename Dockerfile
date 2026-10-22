# syntax=docker/dockerfile:1
ARG WAVELOG_IMAGE=ghcr.io/wavelog/wavelog:3.2.4
ARG PHP_IMAGE=php:8.5-apache-trixie
FROM ${WAVELOG_IMAGE} AS upstream

# Rebuild the runtime independently of the Wavelog release image. Always build --pull.
FROM ${PHP_IMAGE}
COPY --from=upstream /usr/local/bin/install-php-extensions /usr/local/bin/
RUN install-php-extensions curl mysqli mbstring xml zip gd \
    && a2enmod rewrite headers \
    && a2dissite 000-default
COPY --from=upstream /var/www/html/ /var/www/html/
COPY docker/ /opt/wavelog-fc/
RUN set -eu; \
    rm -rf /var/www/html/.git; \
    mkdir -p /opt/wavelog-fc/seed; \
    while IFS= read -r path; do \
      mkdir -p "/var/www/html/$path" "/opt/wavelog-fc/seed/$(dirname "$path")"; \
      mv "/var/www/html/$path" "/opt/wavelog-fc/seed/$path"; \
    done < /opt/wavelog-fc/persistent-dirs; \
    chown -R root:root /var/www/html; \
    chown -R www-data:www-data /var/www/html/application/config; \
    chown -R www-data:www-data /var/www/html/install; \
    cp /opt/wavelog-fc/php.ini "$PHP_INI_DIR/conf.d/zz-fc.ini"; \
    cp /opt/wavelog-fc/apache.conf /etc/apache2/sites-available/wavelog-fc.conf; \
    printf 'Listen 9000\nListen 127.0.0.1:80\n' > /etc/apache2/ports.conf; \
    a2ensite wavelog-fc; \
    chmod +x /opt/wavelog-fc/entrypoint.sh
ENV CI_ENV=docker \
    WAVELOG_GIT_DESCRIBE=3.2.4 \
    WAVELOG_INSTALL_ENABLED=false
WORKDIR /var/www/html
EXPOSE 9000
ENTRYPOINT ["/opt/wavelog-fc/entrypoint.sh"]
CMD ["apache2-foreground"]
