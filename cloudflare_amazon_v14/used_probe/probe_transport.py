"""Low-volume, authenticated Cloudflare Worker probe using curl.

The earlier Python urllib transport got HTTP 403 from the public worker URL,
while curl successfully reached this same endpoint in preceding deployments.
This change makes transport consistent with the verified diagnostic client.
No retries, proxies, user-agent spoofing, redirects, or access-control bypass.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

EXPECTED_HOST = 'egypt-amazon-used-probe.masoud-amazon-eg.workers.dev'


def fetch_json_via_curl(url: str, key: str):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != EXPECTED_HOST:
        raise ValueError('PROBE_URL_NOT_ALLOWED')
    if not key or '\n' in key or '\r' in key:
        raise ValueError('PROBE_KEY_INVALID')
    with tempfile.TemporaryDirectory(prefix='amazon-used-probe-') as temp:
        body = Path(temp) / 'body.json'
        headers = Path(temp) / 'headers.txt'
        cmd = [
            'curl', '--silent', '--show-error', '--max-time', '50',
            '--connect-timeout', '15', '--proto', '=https',
            '--output', str(body), '--dump-header', str(headers),
            '--write-out', '%{http_code}',
            '--header', 'Authorization: Bearer ' + key,
            '--header', 'Accept: application/json', url,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=58, check=False)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise URLError(type(exc).__name__) from exc
        if res.returncode != 0:
            raise URLError('CURL_TRANSPORT_EXIT_' + str(res.returncode))
        code_str = (res.stdout or '').strip()
        if not re.fullmatch(r'\d{3}', code_str):
            raise URLError('CURL_HTTP_STATUS_MISSING')
        status = int(code_str)
        header_text = headers.read_text(errors='replace') if headers.exists() else ''
        info = {}
        for line in header_text.splitlines():
            if ':' not in line:
                continue
            name, value = line.split(':', 1)
            if name.lower() in ('cf-mitigated', 'content-type', 'server'):
                info[name.lower()] = value.strip()[:80]
        if status != 200:
            # Never log the authorization header or the full response body.
            print('USED_PROBE_ENDPOINT_HTTP:', status,
                  'CF_MITIGATED:', info.get('cf-mitigated', 'not-present'),
                  'CONTENT_TYPE:', info.get('content-type', 'unknown'),
                  'SERVER:', info.get('server', 'unknown'), flush=True)
            raise HTTPError(url, status, 'Worker endpoint returned HTTP ' + str(status), {}, None)
        if not body.is_file() or body.stat().st_size > 2_000_000:
            raise ValueError('PROBE_JSON_BODY_MISSING_OR_OVERSIZE')
        data = json.loads(body.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('PROBE_JSON_NOT_OBJECT')
        return data
