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

// clockHit is taller than the drawn time. The bar is 22px and a finger lands below it.
func clockHit() image.Rectangle {
	r := clockRect()
	return image.Rect(0, 0, r.Max.X+8, r.Max.Y+36)
}

func recRect() image.Rectangle {
	return image.Rect(172, 0, 228, statusH)
}

func outTempRect() image.Rectangle {
	return image.Rect(232, 0, W-4, statusH)
}

func dimButton() image.Rectangle {
	return image.Rect(16, 70, W-16, 130)
}

func blankButton() image.Rectangle {
	return image.Rect(16, 146, W-16, lockRect().Min.Y-8)
}

// actionButtons is the right-hand column on a detail page, above the lock.
func actionButtons(n int) []image.Rectangle {
	return pageActionButtons("", n)
}

// pageActionButtons puts the backup actions under the text. Other pages keep the right column.
func pageActionButtons(id string, n int) []image.Rectangle {
	if id == "gpu" {
		// Order is power, Windows, Linux. Power sits on the lock.
		// Windows and Linux share the lock row, same as backup's Run / Wake.
		if n > 3 {
			n = 3
		}
		if n < 1 {
			return nil
		}
		lock := lockRect()
		gap := 6
		// Same size as the lock, sitting on it. The OS buttons match that height.
		power := image.Rect(lock.Min.X, lock.Min.Y-gap-lock.Dy(), lock.Max.X, lock.Min.Y-gap)
		corner := lockHit()
		linuxW := 74
		winW := 96
		linux := image.Rect(corner.Min.X-gap-linuxW, lock.Min.Y, corner.Min.X-gap, lock.Max.Y)
		windows := image.Rect(8, lock.Min.Y, 8+winW, lock.Max.Y)
		if windows.Max.X > linux.Min.X-gap {
			windows.Max.X = linux.Min.X - gap
		}
		out := make([]image.Rectangle, n)
		out[0] = power
		if n > 1 {
			out[1] = windows
		}
		if n > 2 {
			out[2] = linux
		}
		return out
	}
	if n > 2 {
		n = 2
	}
	if n < 1 {
		return nil
	}
	if id == "backup" {
		// Wake GPU shares the lock row. Run backup sits to its left.
		// The text then runs down to that row instead of stopping a band early.
		lock := lockRect()
		gap := 6
		wakeW := 132
		wake := image.Rect(lock.Min.X-gap-wakeW, lock.Min.Y, lock.Min.X-gap, lock.Max.Y)
		run := image.Rect(8, lock.Min.Y, wake.Min.X-gap, lock.Max.Y)
		out := make([]image.Rectangle, n)
		// Actions are wake, then backup. Draw backup on the left, wake next to the lock.
		if n == 1 {
			out[0] = image.Rect(8, lock.Min.Y, lock.Min.X-gap, lock.Max.Y)
			return out
		}
		out[0] = wake
		out[1] = run
		return out
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

// actionHitRect is wider than the drawn button so a tap on the right edge still counts.
func actionHitRect(r image.Rectangle) image.Rectangle {
	x := r.Min.X - 36
	if x < 0 {
		x = 0
	}
	y0 := r.Min.Y - 12
	if y0 < headerH {
		y0 = headerH
	}
	return image.Rect(x, y0, W, r.Max.Y+12)
}

const headerH = 34

// Eateria today / yesterday columns. The gaps are the empty space between them.
const (
	dualLabelX1 = 112
	dualNowX0   = 148
	dualNowX1   = 196
	dualPrevX0  = 236
)

func backRect() image.Rectangle  { return image.Rect(2, 2, 40, headerH) }
func titleRect() image.Rectangle { return image.Rect(44, 2, W-48, headerH) }
func pageRect() image.Rectangle  { return image.Rect(W-42, 2, W-4, headerH) }

func cameraButton() image.Rectangle { return image.Rect(36, 112, W-36, 176) }

func confirmPanel() image.Rectangle { return image.Rect(4, headerH+6, W-4, H-1) }

func confirmButtons() (cancel, ok image.Rectangle) {
	y0 := H - 56
	mid := W / 2
	// Reach the bottom edge. A finger on OK was landing past the old button and counted as No.
	return image.Rect(4, y0, mid-4, H-1), image.Rect(mid+4, y0, W-4, H-1)
}
