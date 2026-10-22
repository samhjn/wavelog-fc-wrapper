<?php
declare(strict_types=1);

// Used before both Wavelog and its installer, without changing upstream files.
$_ENV['CI_ENV'] = 'docker';
$baseUrl = rtrim(getenv('WAVELOG_BASE_URL') ?: '', '/') . '/';
$secure = parse_url($baseUrl, PHP_URL_SCHEME) === 'https';
if ($secure) {
    // TLS terminates at FC. Use configured deployment intent, not client headers.
    $_SERVER['HTTPS'] = 'on';
    ini_set('session.cookie_secure', '1');
}
$assign_to_config = [
    'base_url' => $baseUrl,
    'index_page' => '',
    'sess_driver' => 'files',
    'sess_save_path' => '/mnt/wavelog/sessions',
    'cookie_secure' => $secure,
    'cookie_httponly' => true,
];

if (PHP_SAPI === 'cli') {
    return;
}

// Check the executed file, so direct calls to install/ajax.php are protected too.
$script = $_SERVER['SCRIPT_FILENAME'] ?? '';
if (str_starts_with($script, '/var/www/html/install/')) {
    if (getenv('WAVELOG_INSTALL_ENABLED') !== 'true') {
        http_response_code(403);
        exit('Installer disabled.');
    }
    $expected = getenv('WAVELOG_INSTALL_TOKEN') ?: '';
    if ($expected === '' || !hash_equals($expected, $_SERVER['PHP_AUTH_PW'] ?? '')
        || ($_SERVER['PHP_AUTH_USER'] ?? '') !== 'install') {
        header('WWW-Authenticate: Basic realm="Wavelog setup"');
        http_response_code(401);
        exit('Installer authentication required.');
    }
}

// The upstream master-cron URL is unauthenticated. Public callers must use
// /invoke with the timer secret; only the loopback vhost may call cron/run.
if (($_SERVER['SERVER_PORT'] ?? '') !== '80') {
    $uri = rawurldecode($_SERVER['REQUEST_URI'] ?? '');
    $uri = preg_replace('~/+~', '/', str_replace('?', '/', $uri));
    if (preg_match('~(?:^|/)cron/run(?:/|$|[&;])~i', $uri)) {
        http_response_code(403);
        exit('Use the authenticated timer endpoint.');
    }
}
