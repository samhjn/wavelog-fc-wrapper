<?php
declare(strict_types=1);

function respond(int $status, string $result): never {
    http_response_code($status);
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    echo json_encode(['status' => $result]);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    respond(405, 'method_not_allowed');
}
$body = file_get_contents('php://input', false, null, 0, 4097);
if ($body === false || strlen($body) > 4096) {
    respond(413, 'event_too_large');
}
try {
    $event = json_decode($body, true, 8, JSON_THROW_ON_ERROR);
} catch (JsonException $e) {
    respond(400, 'invalid_event');
}
// FC Timer event: {"triggerName":"...","payload":"<64-char secret>",...}.
// No arbitrary command, route or callback URL is accepted.
$supplied = is_array($event) ? ($event['payload'] ?? null) : null;
$expected = getenv('WAVELOG_CRON_TOKEN') ?: '';
if (!is_string($supplied) || $expected === '' || !hash_equals($expected, $supplied)) {
    respond(403, 'forbidden');
}
if (!is_file('/mnt/wavelog/application/config/docker/config.php')
    || !is_file('/mnt/wavelog/application/config/docker/database.php')) {
    respond(200, 'not_installed');
}
$lock = fopen('/mnt/wavelog/locks/cron.lock', 'c');
if ($lock === false) {
    respond(503, 'lock_unavailable');
}
if (!flock($lock, LOCK_EX | LOCK_NB)) {
    respond(200, 'already_running');
}
// Keep this HTTP invocation active until all work finishes, so FC allocates CPU.
// The OS releases the NAS lock even if FC kills the instance.
$curl = curl_init('http://127.0.0.1/index.php/cron/run');
curl_setopt_array($curl, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 5,
    CURLOPT_TIMEOUT => 840,
    CURLOPT_PROXY => '',
]);
$output = curl_exec($curl);
$status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
if ($status === 429) {
    respond(200, 'rate_limited');
}
if ($output === false || $status < 200 || $status >= 300
    || preg_match('/^ERROR:/m', $output)) {
    // Do not put potentially sensitive upstream output into the HTTP response.
    error_log('Wavelog master cron failed (HTTP ' . $status . '). Check the Cron Manager and application logs.');
    respond(502, 'cron_failed');
}
respond(200, 'ok');
