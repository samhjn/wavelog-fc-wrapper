#!/bin/bash
set -euo pipefail
umask 0027

# Never silently write user data to an ephemeral FC filesystem.
if ! mountpoint -q /mnt/wavelog; then
    echo 'ERROR: mount NAS (or a local Docker volume) at /mnt/wavelog before starting.' >&2
    exit 1
fi
php /opt/wavelog-fc/validate-env.php

# Only the mount root and newly seeded directories need ownership changes.
# FC should mount NAS with userId/groupId 33; Docker volumes initially belong to root.
if [ "$(stat -c '%u:%g' /mnt/wavelog)" != '33:33' ]; then
    chown 33:33 /mnt/wavelog
fi
chmod 0750 /mnt/wavelog

# NFS advisory lock serializes seeding across cold starts. Release before Apache.
exec 9>/mnt/wavelog/.init.lock
flock -w 60 9
mkdir -p /mnt/wavelog/application/config /mnt/wavelog/assets /mnt/wavelog/images
chown 33:33 /mnt/wavelog/application /mnt/wavelog/application/config /mnt/wavelog/assets /mnt/wavelog/images
while IFS= read -r path; do
    target="/mnt/wavelog/$path"
    if [ ! -d "$target" ]; then
        # Rename a completed seed; a killed bootstrap cannot leave half a seed.
        mkdir -p "$(dirname "$target")"
        staging=$(mktemp -d /mnt/wavelog/.seed-XXXXXXXX)
        cp -a "/opt/wavelog-fc/seed/$path/." "$staging/"
        chown -R 33:33 "$staging"
        chmod 0750 "$staging"
        mv "$staging" "$target"
    fi
    ln -sfn "$target" "/var/www/html/$path"
done < /opt/wavelog-fc/persistent-dirs
for path in sessions locks; do
    if [ ! -d "/mnt/wavelog/$path" ]; then
        mkdir "/mnt/wavelog/$path"
        chown 33:33 "/mnt/wavelog/$path"
        chmod 0700 "/mnt/wavelog/$path"
    fi
done
flock -u 9
exec 9>&-

# Verify access as Apache's user, including existing/migrated data.
su -s /bin/sh www-data -c 'test -w /mnt/wavelog/application/config/docker && test -w /mnt/wavelog/sessions && test -w /mnt/wavelog/locks' || {
    echo 'ERROR: NAS directories must be writable by UID/GID 33:33.' >&2
    exit 1
}
if [ -f application/config/docker/config.php ] && [ -f application/config/docker/database.php ]; then
    touch install/.lock
fi
exec docker-php-entrypoint "$@"
