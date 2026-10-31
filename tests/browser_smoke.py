"""Optional browser QA against a disposable running instance, using synthetic data.

HORAS_TEST_URL and HORAS_TEST_PASSWORD must point to a disposable installation:
this test creates and edits sample records. Requires Playwright and Chromium.
"""
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    base = os.environ["HORAS_TEST_URL"]
    password = os.environ["HORAS_TEST_PASSWORD"]
    artifact_dir = Path(os.getenv("HORAS_SCREENSHOTS", "test-results"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"), args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 1150}, locale="es-ES", timezone_id="UTC")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/")
        expect(page).to_have_url(base + "/login")
        page.get_by_label("Contraseña", exact=True).fill(password)
        page.get_by_role("button", name="Entrar").click()
        expect(page.get_by_role("heading", name="Cada hora cuenta.")).to_be_visible()
        page.get_by_role("navigation").get_by_role("link", name="Ajustes", exact=True).click()
        page.get_by_label("Horas por defecto").select_option("2.0")
        page.get_by_label("Tarifa habitual").fill("12,75")
        page.get_by_role("button", name="Guardar preferencias").click()
        page.goto(base + "/?month=2026-10")
        page.locator('form:has(input[name="day"][value="2026-10-05"]) button').click()
        expect(page.get_by_role("link", name="Editar lunes, 5 de octubre de 2026: 2 horas")).to_be_visible()
        page.get_by_role("link", name="Editar lunes, 5 de octubre de 2026: 2 horas").click()
        page.get_by_role("button", name="1,5 h", exact=True).click()
        page.get_by_label("Nota opcional").fill("Apoyo de tarde")
        page.get_by_role("button", name="Guardar registro").click()
        expect(page.get_by_role("link", name="Editar lunes, 5 de octubre de 2026: 1,5 horas")).to_be_visible()
        expect(page.locator(".total-stat strong")).to_have_text("19,13 €")
        page.get_by_role("button", name="Marcar como cobrado").click()
        expect(page.locator(".balance-panel > .badge")).to_have_text("✓ Cobrado")
        page.locator("#quick-hours").select_option("1.5")
        page.locator('form:has(input[name="day"][value="2026-10-07"]) button').click()
        expect(page.locator(".balance-panel > .badge")).to_have_text("◷ Pendiente")
        expect(page.locator(".total-stat strong")).to_have_text("38,25 €")
        # Fill a representative month for screenshots, with no real personal data.
        for day in [1, 2, 8, 12, 14, 15, 19, 20, 21, 26, 28, 29]:
            page.locator('form:has(input[name="day"][value="2026-10-%02d"]) button' % day).click()
        page.locator("#quick-hours").select_option("2.0")
        page.goto(base + "/?month=2026-10")
        page.screenshot(path=str(artifact_dir / "calendario.png"), full_page=False)
        page.get_by_role("link", name="Historial", exact=True).click()
        expect(page.get_by_role("heading", name="Tus horas, con perspectiva.")).to_be_visible()
        expect(page.get_by_role("link", name="Octubre de 2026", exact=True)).to_be_visible()
        page.get_by_role("link", name="Octubre de 2026", exact=True).click()
        with page.expect_download() as download:
            page.get_by_role("link", name="Descargar mes en CSV").click()
        assert download.value.suggested_filename == "horas-2026-10.csv"
        for width in [390, 360, 320]:
            page.set_viewport_size({"width": width, "height": 844})
            page.goto(base + "/?month=2026-10")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"Overflow at {width}"
            expect(page.get_by_role("link", name="Editar lunes, 5 de octubre de 2026: 1,5 horas")).to_be_visible()
            if width == 390:
                page.screenshot(path=str(artifact_dir / "movil.png"), full_page=True)
            page.get_by_role("navigation").get_by_role("link", name="Ajustes", exact=True).click()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.get_by_role("link", name="Calendario", exact=True).click()
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Salir").click()
        expect(page.get_by_role("heading", name="Bienvenido a Horas")).to_be_visible()
        page.screenshot(path=str(artifact_dir / "acceso.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("Navegador: acceso, registro rápido, medias horas, notas, cobros, historial, CSV y móvil a 390/360/320 px verificados.")


if __name__ == "__main__":
    main()
