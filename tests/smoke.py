"""Real Apache/PHP + upstream installer + MariaDB lifecycle test; requires Docker."""
import base64
import http.cookiejar
import json
import re
import secrets
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

IMAGE = sys.argv.pop(1) if len(sys.argv) > 1 else "wavelog-fc:test"


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, text=True, capture_output=True)


class LifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = "wavelog-fc-test-" + secrets.token_hex(4)
        cls.network = cls.prefix + "-net"
        cls.volume = cls.prefix + "-data"
        cls.db = cls.prefix + "-db"
        cls.web = cls.prefix + "-web"
        cls.cron_token = secrets.token_hex(32)
        cls.install_token = secrets.token_hex(32)
        cls.password = secrets.token_hex(16)
        cls.addClassCleanup(cls.cleanup)
        docker("network", "create", cls.network)
        docker("volume", "create", cls.volume)
        docker("run", "-d", "--name", cls.db, "--network", cls.network,
               "--network-alias", "db", "-e", "MARIADB_ROOT_PASSWORD=" + cls.password,
               "-e", "MARIADB_DATABASE=wavelog", "-e", "MARIADB_USER=wavelog",
               "-e", "MARIADB_PASSWORD=" + cls.password, "mariadb:10.11")
        for _ in range(90):
            if cls.sql("SELECT 1", check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("MariaDB failed to start")
        cls.start_web(True)

    @classmethod
    def cleanup(cls):
        for name in (cls.web, cls.db):
            print(docker("logs", "--tail", "100", name, check=False).stdout)
            docker("rm", "-f", name, check=False)
        docker("volume", "rm", cls.volume, check=False)
        docker("network", "rm", cls.network, check=False)

    @classmethod
    def sql(cls, query, check=True):
        return docker("exec", "-e", "MYSQL_PWD=" + cls.password, cls.db,
                      "mariadb", "-uroot", "-N", "wavelog", "-e", query, check=check)

    @classmethod
    def start_web(cls, install):
        docker("run", "-d", "--name", cls.web, "--network", cls.network,
               "-p", "127.0.0.1::9000", "-v", cls.volume + ":/mnt/wavelog",
               "-e", "WAVELOG_BASE_URL=http://localhost/",
               "-e", "WAVELOG_CRON_TOKEN=" + cls.cron_token,
               "-e", "WAVELOG_INSTALL_TOKEN=" + cls.install_token,
               "-e", "WAVELOG_INSTALL_ENABLED=" + str(install).lower(), IMAGE)
        cls.url = "http://" + docker("port", cls.web, "9000").stdout.strip()
        cls.cookies = http.cookiejar.CookieJar()
        cls.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.cookies))
        for _ in range(60):
            try:
                if urllib.request.urlopen(cls.url + "/healthz", timeout=2).status == 200:
                    return
            except (OSError, urllib.error.HTTPError):
                time.sleep(1)
        raise RuntimeError("Web container failed readiness: " + docker("logs", cls.web).stderr)

    def request(self, path, data=None, auth=False, headers=None, method=None):
        hdr = dict(headers or {})
        if auth:
            hdr["Authorization"] = "Basic " + base64.b64encode(
                ("install:" + self.install_token).encode()).decode()
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(self.url + path, data=data, headers=hdr, method=method)
        try:
            res = self.client.open(req, timeout=180)
        except urllib.error.HTTPError as exc:
            res = exc
        return res.status, res.read().decode()

    def invoke(self, token=None):
        return self.request("/invoke", json.dumps({"triggerName": "cron", "payload": token or self.cron_token}).encode(),
                            headers={"Content-Type": "application/json"})

    def test_install_timer_and_recreation(self):
        self.assertEqual(self.request("/healthz")[0], 200)
        self.assertEqual(self.request("/install/")[0], 401)
        self.assertEqual(self.request("/install/ajax.php", data={"run_installer_lock": "1"})[0], 401)
        self.assertEqual(self.request("/invoke")[0], 405)
        self.assertEqual(self.invoke("wrong")[0], 403)
        self.assertEqual(self.request("/invoke", b"[")[0], 400)
        self.assertEqual(json.loads(self.invoke()[1])["status"], "not_installed")
        for route in ("/cron/run", "/index.php/cron/run", "/index.php?/cron/run", "/CRON/run"):
            self.assertEqual(self.request(route)[0], 403, route)

        # Exercise upstream's actual CSRF-protected installation handshake.
        code, page = self.request("/install/", auth=True)
        self.assertEqual(code, 200)
        form_token = re.search(r'name="form_token"[^>]*value="([a-f0-9]+)"', page).group(1)
        data = dict(db_hostname="db", db_name="wavelog", db_username="wavelog",
                    db_password=self.password, directory="", firstname="Test", lastname="Operator",
                    username="testadmin", callsign="N0CALL", password=self.password,
                    cnfm_password=self.password, userlocator="AA00AA", user_email="test@example.com",
                    timezone="0", websiteurl="http://localhost/", global_call_lookup="",
                    log_threshold="1", dxcc="291", city="Test", userlanguage="english",
                    form_token=form_token)
        code, page = self.request("/install/run.php", data, auth=True)
        self.assertEqual(code, 200)
        token = re.search(r"let _installer_token = '([a-f0-9]+)'", page).group(1)
        payload = {"data[" + key + "]": value for key, value in data.items()}
        for step in ("run_config_file", "run_database_file", "run_database_tables", "run_installer_lock"):
            code, body = self.request("/install/ajax.php", {**payload, step: "1"}, auth=True,
                                      headers={"X-Installer-Token": token})
            self.assertEqual((code, body.strip()), (200, "success"), step + ": " + body)

        # A real CI bootstrap runs migrations and creates sessions on NAS.
        code, page = self.request("/index.php/user/login")
        self.assertEqual(code, 200, page[:1000])
        self.assertIn('name="user_name"', page)
        # Avoid contacting external logbook services in CI.
        self.sql("UPDATE cron SET enabled = 0")
        code, body = self.invoke()
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["status"], "ok")
        self.assertEqual(json.loads(self.invoke()[1])["status"], "rate_limited")

        # Cross-request cookie/session storage and arbitrary uploaded data survive
        # destruction of the container, not merely restarting its process.
        marker = secrets.token_hex(16)
        php = ('$s="fcwrapperpersist"; session_id($s); session_start(); '
               '$_SESSION["marker"]="' + marker + '"; session_write_close(); '
               'file_put_contents("/var/www/html/uploads/persist.txt", "' + marker + '");')
        docker("exec", "--user", "33:33", self.web, "php", "-r", php)
        # Uploaded PHP and .htaccess must never become executable configuration.
        docker("exec", self.web, "sh", "-c",
               "printf '<?php echo 12345;' > uploads/unsafe.php; printf 'Require all granted' > uploads/.htaccess")
        self.assertEqual(self.request("/uploads/unsafe.php")[0], 403)
        self.assertEqual(self.request("/uploads/.htaccess")[0], 403)
        self.assertEqual(self.request("/application/config/docker/config.php")[0], 403)
        before = docker("exec", self.web, "sha256sum", "application/config/docker/config.php").stdout
        docker("rm", "-f", self.web)
        self.start_web(False)
        self.assertEqual(self.request("/install/", auth=True)[0], 403)
        self.assertEqual(self.request("/uploads/persist.txt"), (200, marker))
        after = docker("exec", self.web, "sha256sum", "application/config/docker/config.php").stdout
        self.assertEqual(before, after)
        result = docker("exec", "--user", "33:33", self.web, "php", "-r",
                        'session_id("fcwrapperpersist"); session_start(); echo $_SESSION["marker"];').stdout
        self.assertEqual(result, marker)
        self.assertEqual(self.request("/index.php/user/login")[0], 200)

    def test_missing_mount_fails_closed(self):
        result = docker("run", "--rm", IMAGE, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mount NAS", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
