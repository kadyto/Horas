"""Exercise the production image on the local Docker daemon without external services."""
import http.cookiejar
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def run(*args, check=True):
    result = subprocess.run(["docker", "--host=unix:///var/run/docker.sock", *args],
                            text=True, capture_output=True, check=check)
    return result.stdout.strip()


def main():
    name = "horas-test-" + uuid.uuid4().hex[:10]
    volume = name + "-data"
    password = "".join(secrets.choice("0123456789") for _ in range(4))
    # Supply the disposable password through the child environment, not its arguments.
    os.environ["APP_PASSWORD"] = password
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))

    def start():
        run("run", "-d", "--name", name, "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
            "-e", "APP_PASSWORD", "-v", volume + ":/data", "-p", "127.0.0.1::8000", "horas:test")
        port = run("port", name, "8000/tcp").rsplit(":", 1)[1]
        base = "http://127.0.0.1:" + port
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                with opener.open(base + "/healthz", timeout=2) as response:
                    if response.status == 200:
                        return base
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.25)
        raise AssertionError("El contenedor no respondió al healthcheck.")

    def get(path):
        return opener.open(base + path, timeout=5)

    def csrf(page):
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    def post(path, **data):
        return opener.open(base + path, data=urllib.parse.urlencode(data).encode(), timeout=10)

    try:
        run("volume", "create", volume)
        base = start()
        assert run("exec", name, "id", "-u") == "10001"
        page = get("/")
        assert page.url.endswith("/login")
        login_html = page.read().decode()
        logged_in = post("/login", csrf=csrf(login_html), password=password).read().decode()
        assert "Cálculo de horas mensuales" in logged_in
        page = post("/entries/quick", csrf=csrf(logged_in), day="2026-10-01", hours="1.5").read().decode()
        post("/month/rate", csrf=csrf(page), month="2026-10", rate="12.75").close()
        payload = json.loads(get("/backup.json").read())
        assert payload["entries"] == [{"day": "2026-10-01", "minutes": 90, "note": ""}]
        assert "19,13 €" in get("/?month=2026-10").read().decode()
        run("stop", "--time", "10", name)
        run("rm", name)
        base = start()
        # Both the records and the existing signed session survive recreation.
        assert json.loads(get("/backup.json").read()) == payload
        assert get("/history?year=2026").status == 200
        key_mode = run("exec", name, "stat", "-c", "%a", "/data/.session-key")
        assert key_mode == "600"
        print("Docker: acceso privado, UID sin privilegios, 1,5 h, tarifa, cálculo y persistencia verificados.")
    except Exception:
        print(run("logs", "--tail", "35", name, check=False))
        raise
    finally:
        run("rm", "-f", name, check=False)
        run("volume", "rm", volume, check=False)


if __name__ == "__main__":
    main()
