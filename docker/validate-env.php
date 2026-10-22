<?php
declare(strict_types=1);

$url = getenv('WAVELOG_BASE_URL') ?: '';
$parts = parse_url($url);
if (!filter_var($url, FILTER_VALIDATE_URL) || !is_array($parts)
    || !in_array($parts['scheme'] ?? '', ['http', 'https'], true)
    || isset($parts['user'], $parts['pass']) || isset($parts['user'])
    || isset($parts['query']) || isset($parts['fragment'])
    || !in_array($parts['path'] ?? '', ['', '/'], true)) {
    fwrite(STDERR, "ERROR: WAVELOG_BASE_URL must be a root HTTP(S) URL, e.g. https://log.example.com/\n");
    exit(1);
}
foreach (['WAVELOG_CRON_TOKEN', 'WAVELOG_INSTALL_TOKEN'] as $name) {
    if ($name === 'WAVELOG_INSTALL_TOKEN' && getenv('WAVELOG_INSTALL_ENABLED') !== 'true') {
        continue;
    }
    if (!preg_match('/\A[a-f0-9]{64}\z/', getenv($name) ?: '')) {
        fwrite(STDERR, "ERROR: $name must be 64 lowercase hex characters (openssl rand -hex 32).\n");
        exit(1);
    }
}
if (!in_array(getenv('WAVELOG_INSTALL_ENABLED') ?: 'false', ['true', 'false'], true)) {
    fwrite(STDERR, "ERROR: WAVELOG_INSTALL_ENABLED must be true or false.\n");
    exit(1);
}
