package main

import "image"

// Touch chip is mounted for the panel's portrait axes. The LCD is landscape
// (MADCTL 0x28), which is the same swap the hat's ads7846 overlay uses.
// Four corner samples replace this guess and keep whichever axis actually moves.

type calFile struct {
	X0, X1, Y0, Y1 int
	Swap           bool
}

var hwCal = defaultCal()

func defaultCal() calFile {
	// Endpoints swapped once for the 180 degree panel (MADCTL 0xE8).
	return flipCal(calFile{X0: 3900, X1: 200, Y0: 200, Y1: 3900, Swap: true})
}

func flipCal(c calFile) calFile {
	return calFile{X0: c.X1, X1: c.X0, Y0: c.Y1, Y1: c.Y0, Swap: c.Swap}
}

func axisScale(raw, a, b, span int) int {
	if a == b || span < 2 {
		return 0
	}
	v := (raw - a) * (span - 1) / (b - a)
	if v < 0 {
		return 0
	}
	if v >= span {
		return span - 1
	}
	return v
}

func mapCal(rawX, rawY int, c calFile) (int, int) {
	if c.X1 == c.X0 || c.Y1 == c.Y0 {
		c = defaultCal()
	}
	var x, y int
	if c.Swap {
		x = axisScale(rawY, c.Y0, c.Y1, W)
		y = axisScale(rawX, c.X0, c.X1, H)
	} else {
		x = axisScale(rawX, c.X0, c.X1, W)
		y = axisScale(rawY, c.Y0, c.Y1, H)
	}
	return x, y
}

// pts are raw samples at screen corners: top-left, top-right, bottom-left, bottom-right.
func calFromPoints(pts [4][2]int) calFile {
	avg := func(a, b int) int { return (a + b) / 2 }
	leftX := avg(pts[0][0], pts[2][0])
	rightX := avg(pts[1][0], pts[3][0])
	leftY := avg(pts[0][1], pts[2][1])
	rightY := avg(pts[1][1], pts[3][1])
	topX := avg(pts[0][0], pts[1][0])
	botX := avg(pts[2][0], pts[3][0])
	topY := avg(pts[0][1], pts[1][1])
	botY := avg(pts[2][1], pts[3][1])
	if absInt(rightY-leftY) > absInt(rightX-leftX) {
		return calFile{X0: topX, X1: botX, Y0: leftY, Y1: rightY, Swap: true}
	}
	return calFile{X0: leftX, X1: rightX, Y0: topY, Y1: botY, Swap: false}
}

func absInt(v int) int {
	if v < 0 {
		return -v
	}
	return v
}

func rectDist(r image.Rectangle, x, y int) int {
	dx, dy := 0, 0
	if x < r.Min.X {
		dx = r.Min.X - x
	} else if x >= r.Max.X {
		dx = x - (r.Max.X - 1)
	}
	if y < r.Min.Y {
		dy = r.Min.Y - y
	} else if y >= r.Max.Y {
		dy = y - (r.Max.Y - 1)
	}
	if dx > dy {
		return dx
	}
	return dy
}

func nearestTile(x, y, n int) int {
	if y < statusH {
		return -1
	}
	best, bestd := -1, 1<<30
	if n > 8 {
		n = 8
	}
	for i := 0; i < n; i++ {
		d := rectDist(tileRect(i), x, y)
		if d < bestd {
			best, bestd = i, d
		}
	}
	if best >= 0 && bestd <= 16 {
		return best
	}
	return -1
}

func median5(s [5]int) int {
	a := s
	for i := 1; i < 5; i++ {
		v := a[i]
		j := i
		for j > 0 && a[j-1] > v {
			a[j] = a[j-1]
			j--
		}
		a[j] = v
	}
	return a[2]
}
