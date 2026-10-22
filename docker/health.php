<?php
declare(strict_types=1);
// Readiness intentionally does not depend on the DB or a completed installation.
$ready = is_writable('/mnt/wavelog/sessions') && is_writable('/mnt/wavelog/application/config/docker');
http_response_code($ready ? 200 : 503);
header('Content-Type: application/json');
header('Cache-Control: no-store');
echo json_encode(['status' => $ready ? 'ok' : 'storage_unavailable']);
