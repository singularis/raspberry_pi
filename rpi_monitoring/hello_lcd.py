#!/usr/bin/env python3
"""Hello World + touch test on LCDWiki 2.4" ILI9341 / XPT2046 (MPI2411).

LCD: SPI0 CE0, DC=22, RST=27. Touch: SPI0 CE1, IRQ=17 (active low).
"""

import json
import os
import time

import RPi.GPIO as GPIO
import spidev
from PIL import Image, ImageDraw, ImageFont

_SET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setting", "display.json")
with open(_SET, encoding="utf-8") as _f:
    _C = json.load(_f)

DC = _C["pins_bcm"]["lcd_dc"]
RST = _C["pins_bcm"]["lcd_rst"]
IRQ = _C["pins_bcm"]["touch_irq"]
SPI_HZ = int(_C["spi"]["lcd_hz"])
TOUCH_HZ = int(_C["spi"]["touch_hz"])
ROT = int(_C["rot"])
MADCTL = (0x48, 0x28, 0x88, 0xE8)
RAW_MIN = int(_C["touch"]["raw_min"])
RAW_MAX = int(_C["touch"]["raw_max"])
Z_MIN = int(_C["touch"]["z_min"])
BTN_H = 110


def _size(rot):
    return (320, 240) if rot & 1 else (240, 320)


def _spi(dev, hz):
    s = spidev.SpiDev()
    s.open(0, dev)
    s.mode = 0
    s.max_speed_hz = hz
    s.no_cs = False
    return s


def _w(spi, dc, buf):
    GPIO.output(DC, dc)
    mv = memoryview(buf)
    for i in range(0, len(mv), 4096):
        chunk = mv[i:i + 4096]
        if hasattr(spi, "writebytes2"):
            spi.writebytes2(chunk)
        else:
            spi.writebytes(list(chunk))


def cmd(spi, c, *args):
    _w(spi, 0, bytes([c]))
    if args:
        _w(spi, 1, bytes(args))


def init(spi):
    GPIO.output(RST, 0)
    time.sleep(0.05)
    GPIO.output(RST, 1)
    time.sleep(0.12)
    cmd(spi, 0x01)
    time.sleep(0.15)
    cmd(spi, 0x11)
    time.sleep(0.12)
    cmd(spi, 0x3A, 0x55)
    cmd(spi, 0x36, MADCTL[ROT])
    cmd(spi, 0xB1, 0x00, 0x18)
    cmd(spi, 0x29)
    time.sleep(0.02)


def window(spi, x0, y0, x1, y1):
    cmd(spi, 0x2A, x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)
    cmd(spi, 0x2B, y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)
    cmd(spi, 0x2C)


def rgb565(img):
    px = img.convert("RGB").tobytes()
    out = bytearray(len(px) // 3 * 2)
    j = 0
    for i in range(0, len(px), 3):
        r, g, b = px[i], px[i + 1], px[i + 2]
        c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[j] = c >> 8
        out[j + 1] = c & 0xFF
        j += 2
    return out


def show_raw(spi, w, h, data):
    window(spi, 0, 0, w - 1, h - 1)
    _w(spi, 1, data)


def _font(size):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
        )
    except OSError:
        return ImageFont.load_default()


def _center(draw, text, font, fill, w, h, y=None):
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = (w - tw) / 2
    if y is None:
        y = (h - th) / 2 - box[1]
    else:
        y = y - box[1]
    draw.text((x, y), text, fill=fill, font=font)


def btn_rect(w, h):
    return (12, h - BTN_H - 10, w - 12, h - 10)


def home_img(w, h):
    img = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    _center(draw, "Hello World", _font(32), (255, 255, 255), w, h, y=h // 2 - 50)
    x0, y0, x1, y1 = btn_rect(w, h)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=(0, 90, 200))
    _center(draw, "Test touch", _font(22), (255, 255, 255), w, h, y=(y0 + y1) // 2 - 12)
    return img


def ok_img(w, h):
    img = Image.new("RGB", (w, h), (0, 80, 0))
    draw = ImageDraw.Draw(img)
    _center(draw, "touch working", _font(28), (255, 255, 255), w, h)
    return img


def _read12(spi, c):
    r = spi.xfer2([c, 0x00, 0x00])
    return ((r[1] << 8) | r[2]) >> 3


def _map(raw, span):
    v = (raw - RAW_MIN) * (span - 1) / float(RAW_MAX - RAW_MIN)
    return max(0, min(span - 1, int(v)))


def _pressed(touch):
    if GPIO.input(IRQ) == 0:
        return True
    return _read12(touch, 0xB0) > Z_MIN


def touch_xy(touch, w, h):
    if not _pressed(touch):
        return None
    xs, ys, zs = [], [], []
    for _ in range(5):
        zs.append(_read12(touch, 0xB0))
        xs.append(_read12(touch, 0xD0))
        ys.append(_read12(touch, 0x90))
    z = sorted(zs)[2]
    if z < Z_MIN and GPIO.input(IRQ):
        return None
    raw_x = sorted(xs)[2]
    raw_y = sorted(ys)[2]
    x = _map(raw_x, w)
    y = h - 1 - _map(raw_y, h)
    return x, y, raw_x, raw_y, z


def wait_release(touch):
    t0 = time.monotonic()
    while _pressed(touch):
        if time.monotonic() - t0 > 2:
            break
        time.sleep(0.02)


def main():
    w, h = _size(ROT)
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(DC, GPIO.OUT)
    GPIO.setup(RST, GPIO.OUT)
    GPIO.setup(IRQ, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    lcd = _spi(0, SPI_HZ)
    touch = _spi(1, TOUCH_HZ)
    print("building frames...", flush=True)
    home = rgb565(home_img(w, h))
    ok = rgb565(ok_img(w, h))
    try:
        init(lcd)
        show_raw(lcd, w, h, home)
        print("ok", w, "x", h, "tap the blue button (or anywhere)", flush=True)
        while True:
            pt = touch_xy(touch, w, h)
            if pt:
                print("tap", pt, flush=True)
                show_raw(lcd, w, h, ok)
                time.sleep(3)
                show_raw(lcd, w, h, home)
                wait_release(touch)
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("stop", flush=True)
    finally:
        touch.close()
        lcd.close()


if __name__ == "__main__":
    main()
