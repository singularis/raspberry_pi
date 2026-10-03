//go:build pi

package main

import (
	"encoding/json"
	"fmt"
	"image"
	"os"
	"time"

	"periph.io/x/conn/v3/gpio"
	"periph.io/x/conn/v3/gpio/gpioreg"
	"periph.io/x/conn/v3/physic"
	"periph.io/x/conn/v3/spi"
	"periph.io/x/conn/v3/spi/spireg"
	"periph.io/x/host/v3"
)

type panel struct {
	spi spi.Conn
	dc  gpio.PinOut
	rst gpio.PinOut
	buf []byte
}

func (p panel) Close() {}

func (p panel) cmd(c byte, args ...byte) {
	p.dc.Out(gpio.Low)
	_ = p.spi.Tx([]byte{c}, nil)
	if len(args) > 0 {
		p.dc.Out(gpio.High)
		_ = p.spi.Tx(args, nil)
	}
}

func (p *panel) Blit(img *image.RGBA) {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	p.cmd(0x2A, 0, 0, byte((w-1)>>8), byte(w-1))
	p.cmd(0x2B, 0, 0, byte((h-1)>>8), byte(h-1))
	p.cmd(0x2C)
	p.dc.Out(gpio.High)
	n := w * h * 2
	if cap(p.buf) < n {
		p.buf = make([]byte, n)
	}
	buf := p.buf[:n]
	pix := img.Pix
	stride := img.Stride
	j := 0
	for y := 0; y < h; y++ {
		row := pix[y*stride : y*stride+w*4]
		for x := 0; x < w; x++ {
			i := x * 4
			v := uint16(row[i]&0xF8)<<8 | uint16(row[i+1]&0xFC)<<3 | uint16(row[i+2])>>3
			buf[j] = byte(v >> 8)
			buf[j+1] = byte(v)
			j += 2
		}
	}
	const chunk = 4096
	for i := 0; i < len(buf); i += chunk {
		n := i + chunk
		if n > len(buf) {
			n = len(buf)
		}
		_ = p.spi.Tx(buf[i:n], nil)
	}
}

type touchDev struct {
	spi spi.Conn
	irq gpio.PinIn
	cal calFile
	tx  [3]byte
	rx  [3]byte
}

type touchEv struct {
	X, Y       int
	RawX, RawY int
	Down       bool
}

func (t *touchDev) Poll() (touchEv, bool) {
	// One pressure read while idle. The full 5-sample median runs only after a touch.
	if t.read(0xB0) <= 80 {
		return touchEv{}, false
	}
	var zs, xs, ys [5]int
	for i := 0; i < 5; i++ {
		zs[i] = t.read(0xB0)
		xs[i] = t.read(0xD0)
		ys[i] = t.read(0x90)
	}
	if median5(zs) <= 80 {
		return touchEv{}, false
	}
	rx, ry := median5(xs), median5(ys)
	x, y := mapCal(rx, ry, hwCal)
	return touchEv{X: x, Y: y, RawX: rx, RawY: ry, Down: true}, true
}

func (t *touchDev) read(cmd byte) int {
	t.tx[0], t.tx[1], t.tx[2] = cmd, 0, 0
	t.rx[0], t.rx[1], t.rx[2] = 0, 0, 0
	_ = t.spi.Tx(t.tx[:], t.rx[:])
	return int(uint16(t.rx[1])<<8|uint16(t.rx[2])) >> 3
}

func openHardware() (panel, touchDev, error) {
	if _, err := host.Init(); err != nil {
		return panel{}, touchDev{}, err
	}
	dc := gpioreg.ByName("GPIO22")
	rst := gpioreg.ByName("GPIO27")
	irq := gpioreg.ByName("GPIO17")
	if dc == nil || rst == nil {
		return panel{}, touchDev{}, fmt.Errorf("gpio missing")
	}
	_ = dc.Out(gpio.Low)
	_ = rst.Out(gpio.Low)
	time.Sleep(50 * time.Millisecond)
	_ = rst.Out(gpio.High)
	time.Sleep(120 * time.Millisecond)
	lcdPort, err := spireg.Open("SPI0.0")
	if err != nil {
		return panel{}, touchDev{}, err
	}
	lcd, err := lcdPort.Connect(16*physic.MegaHertz, spi.Mode0, 8)
	if err != nil {
		return panel{}, touchDev{}, err
	}
	p := panel{spi: lcd, dc: dc, rst: rst}
	p.cmd(0x01)
	time.Sleep(150 * time.Millisecond)
	p.cmd(0x11)
	time.Sleep(120 * time.Millisecond)
	p.cmd(0x3A, 0x55)
	p.cmd(0x36, 0x28) // MV|BGR landscape. Another 180 from 0xE8.
	p.cmd(0xB1, 0x00, 0x18)
	p.cmd(0x53, 0x2C)
	p.cmd(0x51, 0xE0) // day ~7/8 if the hat wires brightness
	p.cmd(0x29)
	tp, err := spireg.Open("SPI0.1")
	if err != nil {
		return panel{}, touchDev{}, err
	}
	ts, err := tp.Connect(500*physic.KiloHertz, spi.Mode0, 8)
	if err != nil {
		return panel{}, touchDev{}, err
	}
	var in gpio.PinIn
	if irq != nil {
		in = irq
		// Edges were unused and woke a kernel thread. Keep the pin pulled up only.
		_ = irq.In(gpio.PullUp, gpio.NoEdge)
	}
	return p, touchDev{spi: ts, irq: in, cal: hwCal}, nil
}

func calPath() string {
	return "/home/dante/raspberry_pi/setting/display.json"
}

func loadCal(a *App) {
	b, err := os.ReadFile(calPath())
	if err != nil {
		return
	}
	var doc map[string]any
	if json.Unmarshal(b, &doc) != nil {
		return
	}
	touch, _ := doc["touch"].(map[string]any)
	if touch == nil {
		return
	}
	cal, _ := touch["cal"].(map[string]any)
	if cal == nil {
		return
	}
	c := calFile{
		X0: num(cal["x0"]), X1: num(cal["x1"]),
		Y0: num(cal["y0"]), Y1: num(cal["y1"]),
		Swap: cal["swap"] == true || num(cal["swap"]) == 1,
	}
	// rot 3 was saved for MADCTL 0xE8. Flip that cal once for 0x28.
	if num(cal["rot"]) == 3 {
		c = flipCal(c)
		swap := 0
		if c.Swap {
			swap = 1
		}
		touch["cal"] = map[string]int{"x0": c.X0, "x1": c.X1, "y0": c.Y0, "y1": c.Y1, "swap": swap, "rot": 1}
		if out, err := json.MarshalIndent(doc, "", "  "); err == nil {
			_ = os.WriteFile(calPath(), out, 0o644)
		}
	}
	hwCal = c
	a.CalSaved = true
}

func num(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	default:
		return 0
	}
}

func saveCal(a *App) {
	b, err := os.ReadFile(calPath())
	if err != nil {
		return
	}
	var doc map[string]any
	if json.Unmarshal(b, &doc) != nil {
		return
	}
	touch, _ := doc["touch"].(map[string]any)
	if touch == nil {
		touch = map[string]any{}
		doc["touch"] = touch
	}
	c := calFromPoints(a.CalRaw)
	if c.X0 == 0 && c.X1 == 0 && c.Y0 == 0 && c.Y1 == 0 {
		c = defaultCal()
	}
	hwCal = c
	swap := 0
	if c.Swap {
		swap = 1
	}
	touch["cal"] = map[string]int{"x0": c.X0, "x1": c.X1, "y0": c.Y0, "y1": c.Y1, "swap": swap, "rot": 1}
	out, _ := json.MarshalIndent(doc, "", "  ")
	_ = os.WriteFile(calPath(), out, 0o644)
	a.CalSaved = true
}
