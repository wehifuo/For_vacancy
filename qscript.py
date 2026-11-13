import math
import os
import shutil
import time
from pathlib import Path
import json 

from playwright.sync_api import sync_playwright

PATH_TO_VIDEO_FOLDER = "./video"
VIEWPORT = {"width": 1280, "height": 720}

VIDEO_FPS = 25
ZOOM_FACTOR = 2.0
ZOOM_RAMP_SEC = 0.5

HEADLESS = True
DEMO_ZOOM = True

def _effects_script():
    return r"""
(() => {
  const install = () => {
    if (document.getElementById("__pw_cursor")) return;

    const highlight = document.createElement("div");
    highlight.id = "__pw_highlight";
    Object.assign(highlight.style, {
      position: "fixed",
      left: "0px",
      top: "0px",
      width: "64px",                    
      height: "64px",
      borderRadius: "50%",
      background: "rgba(255, 235, 59, 0.35)",
      pointerEvents: "none",            
      zIndex: "2147483645",             
      transform: "translate(-50%, -50%)",
    });
    document.documentElement.appendChild(highlight);

    const cursor = document.createElement("div");
    cursor.id = "__pw_cursor";
    cursor.innerHTML = `
      <svg width="32" height="32" viewBox="0 0 32 32"
           xmlns="http://www.w3.org/2000/svg">
        <path d="M3 2 L3 25 L9.5 19.5 L14 30 L19 28 L14.5 18 L24 18 Z"
              fill="#ffffff" stroke="#000000" stroke-width="2"
              stroke-linejoin="round"/>
      </svg>`;
    Object.assign(cursor.style, {
      position: "fixed",
      left: "0px",
      top: "0px",
      width: "32px",
      height: "32px",
      pointerEvents: "none",
      zIndex: "2147483647",             
      transform: "translate(-3px, -2px)",
    });
    document.documentElement.appendChild(cursor);

    window.__cursorPos = { x: 0, y: 0 };
    window.addEventListener("mousemove", (event) => {
      window.__cursorPos = { x: event.clientX, y: event.clientY };
      cursor.style.left = event.clientX + "px";
      cursor.style.top = event.clientY + "px";
      highlight.style.left = event.clientX + "px";
      highlight.style.top = event.clientY + "px";
    }, true);

    window.__ripple = (x, y) => {
      const ripple = document.createElement("div");
      Object.assign(ripple.style, {
        position: "fixed",
        left: x + "px",
        top: y + "px",
        width: "32px",
        height: "32px",
        marginLeft: "-16px",
        marginTop: "-16px",
        borderRadius: "50%",
        border: "2px solid #ff3b30",
        pointerEvents: "none",
        zIndex: "2147483646",
        transform: "scale(0.2)",
        opacity: "0.9",
      });
      document.documentElement.appendChild(ripple);
      ripple.animate(
        [
          { transform: "scale(0.2)", opacity: 0.9 },
          { transform: "scale(1.6)", opacity: 0 },
        ],
        { duration: 600, easing: "ease-out" },
      ).onfinish = () => ripple.remove();
    };

    const zoomColors = { in: "#00c853", out: "#ff3b30" };

    const showZoomRing = (x, y, type) => {
      const color = zoomColors[type] || "#ffffff";
      const ring = document.createElement("div");
      ring.textContent = type === "in" ? "ZOOM IN" : "ZOOM OUT";

      Object.assign(ring.style, {
        position: "fixed",
        left: x + "px",
        top: y + "px",
        width: "140px",
        height: "140px",
        display: "grid",
        placeItems: "center",
        borderRadius: "50%",
        border: "4px solid " + color,
        color: color,
        font: "bold 14px sans-serif",
        background: "rgba(0, 0, 0, 0.15)",
        boxShadow: "0 0 0 2px rgba(0, 0, 0, 0.5)",
        pointerEvents: "none",
        zIndex: "2147483647",
        transform: "translate(-50%, -50%) scale(0.55)",
        opacity: "0.95",
      });

      document.documentElement.appendChild(ring);

      ring.animate(
        [
          { transform: "translate(-50%, -50%) scale(0.55)", opacity: 0.95 },
          { transform: "translate(-50%, -50%) scale(1.15)", opacity: 0 },
        ],
        { duration: 800, easing: "ease-out" },
      ).onfinish = () => ring.remove();
    };

    window.__zoomAt = (x, y) => {
      const toggle = window.__recordZoomToggle;

      if (typeof toggle !== "function") {
        console.warn("zoom capture is not ready");
        return null;
      }

      return Promise.resolve(toggle(x, y)).then((type) => {
        showZoomRing(x, y, type);
        return type;
      });
    };

    window.addEventListener("keydown", (event) => {
      if (event.key !== "F5" || event.repeat) return;

      event.preventDefault();
      event.stopPropagation();

      const point = window.__cursorPos || { x: 0, y: 0 };
      window.__zoomAt(point.x, point.y);
    }, true);
    window.ShowCallout = (text, bgColor, textColor, fade) => {
      const box = document.createElement("div");
      box.textContent = text;
      Object.assign(box.style, {
        position: "fixed",
        left: "40px",
        top: "100px",
        padding: "10px 16px",
        background: bgColor,
        color: textColor,
        font: "16pt sans-serif",
        border: "1px solid rgba(0,0,0,.25)",
        borderRadius: "6px",
        pointerEvents: "none",
        zIndex: "2147483647",
        opacity: fade ? "0" : "1",
        transition: fade ? "opacity 0.4s ease" : "none",
      });
      document.documentElement.appendChild(box);

      if (fade) {
        requestAnimationFrame(() => { box.style.opacity = "1"; });
      }
      
      // исчезание   
      const visibleMs = (fade ? 400 : 0) + 2500;
      setTimeout(() => {
        if (!fade) {
          box.remove();
          return;
        }
        box.style.transition = "opacity 2s ease";
        box.style.opacity = "0";
        setTimeout(() => box.remove(), 2000);
      }, visibleMs);
    };
  };

  if (document.documentElement) install();
  else document.addEventListener("DOMContentLoaded", install, { once: true });
})();
"""


def _move_mouse(page, target_x, target_y, duration_ms=700, steps=45):
    start = page.evaluate("() => window.__cursorPos") or {"x": 0, "y": 0}

    for step in range(1, steps + 1):
        progress = step / steps
        eased = 0.5 - math.cos(math.pi * progress) / 2

        x = start["x"] + (target_x - start["x"]) * eased
        y = start["y"] + (target_y - start["y"]) * eased

        page.mouse.move(x, y)
        time.sleep(duration_ms / 1000 / steps)

    page.mouse.move(target_x, target_y)  # для подстраховки


def _center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _zoom_at(page, x, y):
    try:
        page.evaluate(
            "(point) => window.__zoomAt(point.x, point.y)",
            {"x": float(x), "y": float(y)},
        )
    except Exception as error:
        print(f"Не удалось переключить зум: {error}")


def _show_callout(page, text, bg_color="#FFEB3B", text_color="#000000", fade=True):
    page.evaluate(
        "(args) => window.ShowCallout(args.text, args.bgColor, args.textColor, args.fade)",
        {
            "text": text,
            "bgColor": bg_color,
            "textColor": text_color,
            "fade": fade,
        },
    )


def _click_with_ripple(page, x, y, pause_ms=250):
    page.evaluate("(point) => window.__ripple(point.x, point.y)", {"x": x, "y": y})
    if pause_ms:
        page.wait_for_timeout(pause_ms)
    page.mouse.click(x, y)


def CaptureVideo_Magento(url, company_name, language, country, postcode, city, street, house_no):

    video_dir = Path(PATH_TO_VIDEO_FOLDER).resolve()
    video_dir.mkdir(parents=True, exist_ok=True)

    destination = video_dir / f"{company_name}.webm"
    sidecar_path = Path(str(destination) + ".zoom.json")
    sidecar_path.unlink(missing_ok=True)

    zoom_events = []
    zoom_active = False
    t0 = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, channel="chromium")

        version = browser.version.split(".")[0]
        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        )

        context = browser.new_context(
            user_agent=user_agent,
            viewport=VIEWPORT,
            record_video_dir=str(video_dir),
            record_video_size=VIEWPORT,
        )

        t0 = time.monotonic()

        context.add_init_script(_effects_script())

        page = context.new_page()
        video = page.video
        success = False

        def record_zoom_toggle(x, y):
            nonlocal zoom_active

            elapsed = max(0.0, time.monotonic() - t0)
            event_type = "out" if zoom_active else "in"
            zoom_active = not zoom_active

            zoom_events.append(
                {
                    "t": round(elapsed, 3),
                    "x": round(float(x), 2),
                    "y": round(float(y), 2),
                    "type": event_type,
                }
            )

            return event_type

        page.expose_function("__recordZoomToggle", record_zoom_toggle)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_selector('textarea[name="q"]', timeout=30_000)

            _show_callout(page, "Text")

            search_box = page.locator('textarea[name="q"]')
            search_box.scroll_into_view_if_needed()
            box = search_box.bounding_box()
            x, y = _center(box)

            _move_mouse(page, x, y, duration_ms=800)

            zoom_x, zoom_y = x, y
            if DEMO_ZOOM:
                _zoom_at(page, zoom_x, zoom_y)

            _click_with_ripple(page, x, y)

            query = f"Magento developer in {city}"
            page.keyboard.type(query, delay=90)
            page.wait_for_timeout(500)

            submit = page.locator('form button[type="submit"]:visible').last
            submit.wait_for(state="visible", timeout=10_000)
            box = submit.bounding_box()
            x, y = _center(box)

            _move_mouse(page, x, y, duration_ms=600)
            try:
                _click_with_ripple(page, x, y)
            except Exception:
                # нужно чтобы не завершилось с ошибкой уничтожения страницы
                pass

            page.wait_for_selector(
                'a[data-testid="result-title-a"]',
                timeout=45_000,
            )

            if DEMO_ZOOM:
                _zoom_at(page, zoom_x, zoom_y)

            first_result = page.locator('a[data-testid="result-title-a"]').first
            first_result.scroll_into_view_if_needed()
            box = first_result.bounding_box()
            x, y = _center(box)

            _move_mouse(page, x, y, duration_ms=900)
            _click_with_ripple(page, x, y)

            page.wait_for_timeout(2_000)
            success = True

        except Exception as error:
            print(f"[{company_name}] Ошибка: {error}")

        finally:
            context.close()
            browser.close()

        if not success:
            return None

        source = video.path() if video else None
        if not source or not os.path.isfile(source):
            return None

        destination = video_dir / f"{company_name}.webm"
        shutil.move(source, str(destination))

        if zoom_events:
            payload = {
                "viewport": dict(VIEWPORT),
                "fps": VIDEO_FPS,
                "zoom_factor": ZOOM_FACTOR,
                "ramp_sec": ZOOM_RAMP_SEC,
                "events": sorted(zoom_events, key=lambda item: item["t"]),
            }

            tmp_path = Path(str(sidecar_path) + ".tmp")
            try:
                tmp_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp_path.replace(sidecar_path)
            except OSError as error:
                tmp_path.unlink(missing_ok=True)
                print(f"[{company_name}] Ошибка записи sidecar: {error}")

        return str(destination)
