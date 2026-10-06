#!/usr/bin/env python3
"""Живой Playwright 320–1440 для страницы отчёта (рецепт review-acceptance.md, п.3).

Контрольные раскладки (320, 390, 700, 1440): без console-ошибок, полоса управления
не обрезана, страница отвечает на клавиатуру (пробел — пуск). Выход 1 = дефект.

    uv run --with playwright tools/live_layouts.py --url http://localhost:8765/brier/
"""
import argparse, asyncio, sys
from playwright.async_api import async_playwright

WIDTHS = [(320, 568), (390, 844), (700, 390), (1440, 900)]

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    a = ap.parse_args()
    problems = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for w, h in WIDTHS:
            page = await browser.new_page(viewport={"width": w, "height": h}, has_touch=True)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            await page.goto(a.url)
            await page.wait_for_function("typeof P !== 'undefined' && P.audio && P.audio.readyState >= 2")
            clipped = await page.evaluate("""[...document.querySelectorAll('#bar > *, #volume')].filter(e => {
              if (getComputedStyle(e).display === 'none') return false;
              const r = e.getBoundingClientRect();
              return !(r.x >= 0 && r.y >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1);
            }).map(e => e.id || e.className)""")
            if clipped:
                problems.append(f"{w}x{h}: clipped controls: {clipped}")
            # клавиатура: пробел запускает (жест разрешён политикой autoplay)
            await page.keyboard.press(" ")
            await page.wait_for_timeout(400)
            started = await page.evaluate("P.started === true")
            if not started:
                problems.append(f"{w}x{h}: space did not start playback")
            if errors:
                problems.append(f"{w}x{h}: {errors[:4]}")
            await page.close()
        await browser.close()
    for pr in problems:
        print("DEFECT:", pr)
    print("live layouts 320-1440:", "OK" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
