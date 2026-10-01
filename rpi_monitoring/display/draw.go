package main

import (
	"image"
	"image/color"
	"image/draw"
	"strings"

	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"
)

const (
	W = 320
	H = 240
)

type faces struct {
	sans11 font.Face
	sans14 font.Face
	sans17 font.Face
	sans20 font.Face
	sans22 font.Face
	sans28 font.Face
	mono24 font.Face
	mono32 font.Face
	mono48 font.Face
}

func loadFaces() *faces {
	sans := mustFont("fonts/DejaVuSans-Bold.ttf")
	mono := mustFont("fonts/DejaVuSansMono-Bold.ttf")
	mk := func(f *opentype.Font, size float64) font.Face {
		face, err := opentype.NewFace(f, &opentype.FaceOptions{Size: size, DPI: 72, Hinting: font.HintingFull})
		if err != nil {
			panic(err)
		}
		return face
	}
	return &faces{
		sans11: mk(sans, 11),
		sans14: mk(sans, 14),
		sans17: mk(sans, 17),
		sans20: mk(sans, 20),
		sans22: mk(sans, 22),
		sans28: mk(sans, 28),
		mono24: mk(mono, 22),
		mono32: mk(mono, 28),
		mono48: mk(mono, 48),
	}
}

func fill(dst *image.RGBA, r image.Rectangle, c color.Color) {
	draw.Draw(dst, r, &image.Uniform{c}, image.Point{}, draw.Src)
}

func faceH(face font.Face) int {
	m := face.Metrics()
	return m.Ascent.Ceil() + m.Descent.Ceil()
}

func fitPx(face font.Face, s string, maxW int) string {
	if s == "" || maxW <= 1 {
		return ""
	}
	if font.MeasureString(face, s).Ceil() <= maxW {
		return s
	}
	rs := []rune(s)
	lo, hi := 0, len(rs)
	best := ""
	for lo <= hi {
		mid := (lo + hi) / 2
		cand := string(rs[:mid])
		if mid < len(rs) {
			cand += "."
		}
		if font.MeasureString(face, cand).Ceil() <= maxW {
			best = cand
			lo = mid + 1
		} else {
			hi = mid - 1
		}
	}
	return best
}

func wrapPx(face font.Face, s string, maxW, maxLines int) []string {
	if s == "" || maxW <= 1 || maxLines < 1 {
		return nil
	}
	words := strings.Fields(s)
	if len(words) == 0 {
		return nil
	}
	var lines []string
	cur := ""
	flush := func() bool {
		if cur == "" {
			return false
		}
		lines = append(lines, cur)
		cur = ""
		return len(lines) >= maxLines
	}
	for _, w := range words {
		trial := w
		if cur != "" {
			trial = cur + " " + w
		}
		if font.MeasureString(face, trial).Ceil() <= maxW {
			cur = trial
			continue
		}
		if flush() {
			return lines
		}
		cur = fitPx(face, w, maxW)
		if font.MeasureString(face, cur).Ceil() > maxW {
			cur = ""
		}
	}
	flush()
	return lines
}

func text(dst *image.RGBA, face font.Face, s string, x, y int, c color.Color) {
	d := font.Drawer{Dst: dst, Src: &image.Uniform{c}, Face: face, Dot: fixed.P(x, y)}
	d.DrawString(s)
}

type inkBox struct {
	R image.Rectangle
	S string
	F font.Face
}

func textCenter(dst *image.RGBA, face font.Face, s string, r image.Rectangle, c color.Color) {
	w := font.MeasureString(face, s).Ceil()
	m := face.Metrics()
	x := r.Min.X + (r.Dx()-w)/2
	y := r.Min.Y + (r.Dy()+m.Ascent.Ceil()-m.Descent.Ceil())/2
	text(dst, face, s, x, y, c)
}

func spark(dst *image.RGBA, r image.Rectangle, pts []float64, c color.Color) {
	if len(pts) < 2 {
		return
	}
	min, max := pts[0], pts[0]
	for _, p := range pts {
		if p < min {
			min = p
		}
		if p > max {
			max = p
		}
	}
	if max == min {
		max = min + 1
	}
	prev := image.Point{}
	for i, p := range pts {
		x := r.Min.X + i*(r.Dx()-1)/(len(pts)-1)
		y := r.Max.Y - 1 - int((p-min)/(max-min)*float64(r.Dy()-1))
		pt := image.Point{x, y}
		if i > 0 {
			line(dst, prev, pt, c)
		}
		prev = pt
	}
}

func line(dst *image.RGBA, a, b image.Point, c color.Color) {
	dx := abs(b.X - a.X)
	dy := -abs(b.Y - a.Y)
	sx, sy := 1, 1
	if a.X > b.X {
		sx = -1
	}
	if a.Y > b.Y {
		sy = -1
	}
	err := dx + dy
	for {
		if image.Pt(a.X, a.Y).In(dst.Bounds()) {
			dst.Set(a.X, a.Y, c)
		}
		if a == b {
			return
		}
		e2 := 2 * err
		if e2 >= dy {
			err += dy
			a.X += sx
		}
		if e2 <= dx {
			err += dx
			a.Y += sy
		}
	}
}

func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
