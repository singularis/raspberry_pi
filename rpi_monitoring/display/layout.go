package main

import "image"

const (
	statusH = 22
	tileW   = 76
	tileH   = 104
	gap     = 4
	marginX = 2
	gridY   = 26
)

func tileRect(i int) image.Rectangle {
	col, row := i%4, i/4
	x := marginX + col*(tileW+gap)
	y := gridY + row*(tileH+gap)
	return image.Rect(x, y, x+tileW, y+tileH)
}

func statusSummaryRect() image.Rectangle {
	return image.Rect(82, 0, 168, statusH)
}

func lockRect() image.Rectangle {
	return image.Rect(W-44, H-44, W-4, H-4)
}

func lockHit() image.Rectangle {
	return image.Rect(W-78, H-78, W, H)
}

func clockRect() image.Rectangle {
	return image.Rect(4, 0, 78, statusH)
}

func recRect() image.Rectangle {
	return image.Rect(172, 0, 228, statusH)
}

func outTempRect() image.Rectangle {
	return image.Rect(232, 0, W-4, statusH)
}

// actionButtons is the right-hand column on a detail page, above the lock.
func actionButtons(n int) []image.Rectangle {
	if n > 2 {
		n = 2
	}
	if n < 1 {
		return nil
	}
	x0, x1 := 222, W-6
	y0 := headerH + 8
	y1 := lockRect().Min.Y - 8
	gap := 8
	h := (y1 - y0 - gap*(n-1)) / n
	out := make([]image.Rectangle, n)
	for i := 0; i < n; i++ {
		y := y0 + i*(h+gap)
		out[i] = image.Rect(x0, y, x1, y+h)
	}
	return out
}

const headerH = 34

func backRect() image.Rectangle  { return image.Rect(2, 2, 40, headerH) }
func titleRect() image.Rectangle { return image.Rect(44, 2, W-48, headerH) }
func pageRect() image.Rectangle  { return image.Rect(W-42, 2, W-4, headerH) }

func cameraButton() image.Rectangle { return image.Rect(36, 112, W-36, 176) }

func confirmPanel() image.Rectangle { return image.Rect(8, headerH+8, W-8, H-8) }

func confirmButtons() (cancel, ok image.Rectangle) {
	p := confirmPanel()
	y0 := p.Max.Y - 44
	mid := p.Min.X + p.Dx()/2
	return image.Rect(p.Min.X+8, y0, mid-6, p.Max.Y-8), image.Rect(mid+6, y0, p.Max.X-8, p.Max.Y-8)
}
