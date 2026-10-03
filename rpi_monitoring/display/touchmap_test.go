package main

import "testing"

func TestMapLandscapeCorners(t *testing.T) {
	c := defaultCal()
	x, y := mapCal(3900, 200, c)
	if x > 5 || y > 5 {
		t.Fatalf("top-left %d,%d", x, y)
	}
	x, y = mapCal(200, 3900, c)
	if x < W-6 || y < H-6 {
		t.Fatalf("bottom-right %d,%d", x, y)
	}
}

func TestFlipLegacyCal(t *testing.T) {
	old := calFile{X0: 3900, X1: 200, Y0: 200, Y1: 3900, Swap: true}
	x0, y0 := mapCal(3900, 200, old)
	x1, y1 := mapCal(3900, 200, flipCal(old))
	if absInt(x0+x1-(W-1)) > 2 || absInt(y0+y1-(H-1)) > 2 {
		t.Fatalf("flip should be 180 degrees: (%d,%d) -> (%d,%d)", x0, y0, x1, y1)
	}
	if flipCal(flipCal(old)) != old {
		t.Fatal("flip twice")
	}
}

func TestCalFromCorners(t *testing.T) {
	var pts [4][2]int
	pts[0] = [2]int{3900, 200}
	pts[1] = [2]int{3900, 3900}
	pts[2] = [2]int{200, 200}
	pts[3] = [2]int{200, 3900}
	c := calFromPoints(pts)
	if !c.Swap {
		t.Fatal("expected swapped axes")
	}
	x, y := mapCal(2050, 2050, c)
	if absInt(x-W/2) > 30 || absInt(y-H/2) > 30 {
		t.Fatalf("center %d,%d", x, y)
	}
}

func TestNearestTile(t *testing.T) {
	r := tileRect(0)
	if nearestTile(r.Min.X+8, r.Min.Y+8, 8) != 0 {
		t.Fatal("inside tile 0")
	}
	if nearestTile(r.Max.X, r.Min.Y+8, 8) != 0 {
		t.Fatal("just outside tile 0")
	}
	if nearestTile(10, 4, 8) != -1 {
		t.Fatal("status bar is not a tile")
	}
}
