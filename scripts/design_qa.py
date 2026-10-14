"""Design QA: render the three fixture states at 375/768/1280 px in light and dark modes, both modes."""
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"; OUT.mkdir(parents=True, exist_ok=True)
PY = sys.executable
for fixture in ("strong", "none", "stale"):
    build = ROOT / "site" / "build" / fixture
    subprocess.run([PY, str(ROOT / "scripts" / "build_site.py"), "--fixture", fixture, "--out", str(build)], check=True)
with sync_playwright() as p:
    import glob
    import os
    exe = os.environ.get("CHROMIUM_PATH") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome")) + sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/headless_shell"))), None)
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    for fixture in ("strong", "none", "stale"):
        url = (ROOT / "site" / "build" / fixture / "index.html").as_uri()
        for width in (375, 768, 1280):
            for scheme in ("light", "dark"):
                for mode in ("normie", "nerd"):
                    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme, device_scale_factor=1)
                    page = ctx.new_page()
                    page.goto(url + f"?mode={mode}")
                    page.wait_for_timeout(150)
                    if mode == "nerd":
                        page.evaluate("document.querySelectorAll('details.maps-details').forEach(d=>d.open=true)")
                        for img in page.query_selector_all(".map-card img"):
                            img.scroll_into_view_if_needed()
                        page.wait_for_function("[...document.querySelectorAll('.map-card img')].every(i=>i.complete && i.naturalWidth>0)", timeout=15000)
                        page.evaluate("window.scrollTo(0,0)")
                    scroll_w = page.evaluate("document.documentElement.scrollWidth")
                    if scroll_w > width:
                        print(f"WARNING horizontal scroll: {fixture} {width} {scheme} {mode}: scrollWidth={scroll_w}")
                    page.screenshot(path=str(OUT / f"{fixture}-{width}-{scheme}-{mode}.png"), full_page=True)
                    ctx.close()
        # embed + method once
        ctx = browser.new_context(viewport={"width": 420, "height": 400}); page = ctx.new_page()
        page.goto((ROOT / "site" / "build" / fixture / "embed.html").as_uri()); page.screenshot(path=str(OUT / f"{fixture}-embed.png")); ctx.close()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}); page = ctx.new_page()
    page.goto((ROOT / "site" / "build" / "strong" / "method.html").as_uri()); page.screenshot(path=str(OUT / "method-1280-light.png"), full_page=True); ctx.close()
    browser.close()
print("screenshots in", OUT)
