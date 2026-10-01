package main

import (
	"image/png"
	"os"
	"path/filepath"
	"testing"
	"time"

	"golang.org/x/image/font"
)

func boot(t *testing.T, now time.Time, snap *Snapshot) *App {
	t.Helper()
	a := newApp(now)
	a.CalSaved = true
	a.advance(time.Second)
	if a.Screen != scrConnecting && a.Screen != scrHome && a.Screen != scrNight {
		t.Fatalf("boot screen %s", a.Screen)
	}
	a.setSnap(snap, nil)
	return a
}

func tap(a *App, id string) {
	// Find a point that hits id by scanning. Tests use known geometry.
	for y := 0; y < H; y += 2 {
		for x := 0; x < W; x += 2 {
			if a.hit(x, y) == id {
				a.pointerDown(x, y)
				a.pointerUp(x, y)
				return
			}
		}
	}
	a.tap(id)
}

func TestJourneys(t *testing.T) {
	dir := filepath.Join(os.TempDir(), "lcd_journeys")
	if v := os.Getenv("LCD_PREVIEW"); v != "" {
		dir = v
	}
	_ = os.MkdirAll(dir, 0o755)
	day := time.Date(2026, 9, 26, 15, 43, 0, 0, time.UTC)
	night := time.Date(2026, 9, 26, 23, 10, 0, 0, time.UTC)
	snap := baseSnap()

	save := func(name string, a *App) {
		f, err := os.Create(filepath.Join(dir, name+".png"))
		if err != nil {
			t.Fatal(err)
		}
		defer f.Close()
		if err := png.Encode(f, a.Img); err != nil {
			t.Fatal(err)
		}
	}

	// J1 boot to home
	a := boot(t, day, snap)
	if a.Screen != scrHome {
		t.Fatalf("J1 %s", a.Screen)
	}
	save("J1_home", a)

	// J2 open and back each tile
	for i := 0; i < 8; i++ {
		tap(a, "tile:"+itoa(i))
		want := scrDetail
		if snap.Tiles[i].ID == "camera" {
			want = scrCamera
		}
		if a.Screen != want {
			t.Fatalf("J2 tile %d screen %s", i, a.Screen)
		}
		save("J2_tile"+itoa(i), a)
		tap(a, "back")
		if a.Screen != scrHome {
			t.Fatalf("J2 back %s", a.Screen)
		}
	}

	// J3 pages
	tap(a, "tile:0")
	tap(a, "page")
	if a.Page != 1 {
		t.Fatalf("J3 page %d", a.Page)
	}
	save("J3_page2", a)
	tap(a, "page")
	if a.Page != 0 {
		t.Fatalf("J3 back page %d", a.Page)
	}
	tap(a, "back")

	// J4 idle 5s
	tap(a, "tile:1")
	a.advance(6 * time.Second)
	if a.Screen != scrHome {
		t.Fatalf("J4 %s", a.Screen)
	}

	// J5 slide off
	a.pointerDown(tileRect(0).Min.X+4, tileRect(0).Min.Y+4)
	a.pointerUp(0, 0)
	if a.Screen != scrHome {
		t.Fatalf("J5 %s", a.Screen)
	}

	// J7 wake confirm, on the backup screen
	tap(a, "tile:5")
	tap(a, "act:wake")
	if a.Screen != scrConfirm {
		t.Fatalf("J7 confirm %s", a.Screen)
	}
	save("J7_confirm", a)
	a.advance(time.Second)
	tap(a, "ok")
	if a.Toast == "" {
		t.Fatal("J7 no toast")
	}
	save("J7_toast", a)

	// J8 cancel
	a.Toast = ""
	tap(a, "act:wake")
	tap(a, "cancel")
	if a.Screen != scrDetail {
		t.Fatalf("J8 %s", a.Screen)
	}

	// J10 disabled
	a.Snap.Tiles[5].Pages[0].Actions[0].Enabled = false
	a.Snap.Tiles[5].Pages[0].Actions[0].Why = "GPU is on"
	tap(a, "act:wake")
	if a.Screen == scrConfirm {
		t.Fatal("J10 should not confirm")
	}
	if a.Toast == "" {
		t.Fatal("J10 why")
	}
	tap(a, "back")

	// J12 backup confirm
	tap(a, "tile:5")
	tap(a, "act:backup")
	if a.Screen != scrConfirm {
		t.Fatalf("J12 %s", a.Screen)
	}
	tap(a, "cancel")
	tap(a, "back")

	// J14 camera start/stop
	tap(a, "tile:7")
	tap(a, "start")
	if a.Snap.Tiles[7].Camera == nil || !a.Snap.Tiles[7].Camera.Recording {
		t.Fatal("J14 not recording")
	}
	save("J14_rec", a)
	tap(a, "back")
	if !a.recording() {
		t.Fatal("J14 pill")
	}
	tap(a, "tile:7")
	tap(a, "stop")
	if a.Snap.Tiles[7].Camera.Recording {
		t.Fatal("J14 still recording")
	}

	// J18 summary opens worst
	a = boot(t, day, mockSet()["home_mixed"])
	tap(a, "summary")
	if a.Screen != scrDetail || a.cur().ID != "worker" {
		t.Fatalf("J18 %s %v", a.Screen, a.cur())
	}
	save("J18_worker", a)

	// J21 no good fetch for 5 minutes -> bang
	a = boot(t, day, snap)
	a.Mono += linkDead + time.Second
	a.setSnap(nil, errDown{})
	if a.Screen != scrBang {
		t.Fatalf("J21 %s fails=%d", a.Screen, a.Fails)
	}
	save("J21_bang", a)
	tap(a, "bang")
	if a.Screen != scrGrey {
		t.Fatalf("J21 grey %s", a.Screen)
	}
	a.setSnap(snap, nil)
	if a.Screen != scrHome {
		t.Fatalf("J21 recover %s", a.Screen)
	}

	// J22 night
	a = boot(t, night, snap)
	if a.Screen != scrNight {
		t.Fatalf("J22 %s", a.Screen)
	}
	save("J22_night", a)
	tap(a, "night")
	if a.Screen != scrHome {
		t.Fatalf("J22 wake %s", a.Screen)
	}
	save("J22_grid", a)

	// J23 calib first run
	a = newApp(day)
	a.advance(time.Second)
	if a.Screen != scrCalib {
		t.Fatalf("J23 %s", a.Screen)
	}
	save("J23_calib", a)
	for i := 0; i < 5; i++ {
		tap(a, "cross")
	}
	if !a.CalSaved || a.Screen == scrCalib {
		t.Fatalf("J23 done saved=%v screen=%s", a.CalSaved, a.Screen)
	}

	// J27 boot grace stays connecting
	a = newApp(day)
	a.CalSaved = true
	a.advance(time.Second)
	a.Started = a.Mono
	a.setSnap(nil, errDown{})
	if a.Screen == scrBang {
		t.Fatal("J27 bang during grace")
	}
	save("J27_connecting", a)

	// J25 / J26 are collector states; the display only paints them.
	a = boot(t, day, mockSet()["eateria_crit"])
	if a.Snap.Tiles[4].State != "crit" {
		t.Fatal("J25")
	}
	save("J25_eateria", a)
	a = boot(t, day, mockSet()["gpu_claw"])
	save("J26_claw", a)

	// J4 confirm idle
	a = boot(t, day, snap)
	tap(a, "tile:5")
	tap(a, "act:wake")
	a.advance(6 * time.Second)
	if a.Screen != scrHome {
		t.Fatalf("confirm idle %s", a.Screen)
	}
}

type errDown struct{}

func (errDown) Error() string { return "down" }

func itoa(i int) string {
	return string(rune('0' + i))
}

func TestTextBoxes(t *testing.T) {
	day := time.Date(2026, 9, 26, 15, 43, 0, 0, time.UTC)
	night := time.Date(2026, 9, 26, 23, 10, 0, 0, time.UTC)
	snap := baseSnap()
	snap.Tiles[2].L2 = "since 23:00 on schedule"
	snap.Tiles[6].L3 = "wifi -58dBm loss 3%"
	screens := []struct {
		name string
		a    *App
	}{
		{"home", boot(t, day, snap)},
		{"detail", func() *App { a := boot(t, day, snap); tap(a, "tile:0"); return a }()},
		{"confirm", func() *App { a := boot(t, day, snap); tap(a, "tile:5"); tap(a, "act:wake"); return a }()},
		{"backup", func() *App { a := boot(t, day, snap); tap(a, "tile:5"); return a }()},
		{"gpu", func() *App { a := boot(t, day, snap); tap(a, "tile:2"); return a }()},
		{"eateria", func() *App { a := boot(t, day, snap); tap(a, "tile:4"); return a }()},
		{"pi", func() *App { a := boot(t, day, snap); tap(a, "tile:3"); return a }()},
		{"home_rec", func() *App {
			a := boot(t, day, snap)
			a.Snap.Tiles[7].Camera.Recording = true
			a.paint()
			return a
		}()},
		{"camera", func() *App { a := boot(t, day, snap); tap(a, "tile:7"); return a }()},
		{"night", boot(t, night, snap)},
		{"bang", func() *App {
			a := boot(t, day, snap)
			a.Mono += linkDead + time.Second
			a.setSnap(nil, errDown{})
			return a
		}()},
	}
	for _, sc := range screens {
		assertBoxes(t, sc.name, sc.a.boxes)
	}
}

func assertBoxes(t *testing.T, name string, boxes []inkBox) {
	t.Helper()
	if len(boxes) == 0 {
		t.Fatalf("%s drew no text", name)
	}
	for i, b := range boxes {
		if b.R.Dx() < 1 || b.R.Dy() < 1 {
			t.Fatalf("%s empty box %q", name, b.S)
		}
		if w := font.MeasureString(b.F, b.S).Ceil(); w > b.R.Dx() {
			t.Fatalf("%s %q is %dpx in a %dpx box", name, b.S, w, b.R.Dx())
		}
		if b.R.Min.X < 0 || b.R.Min.Y < 0 || b.R.Max.X > W || b.R.Max.Y > H {
			t.Fatalf("%s %q outside screen %v", name, b.S, b.R)
		}
		for j := i + 1; j < len(boxes); j++ {
			if !b.R.Intersect(boxes[j].R).Empty() {
				t.Fatalf("%s %q %v hits %q %v", name, b.S, b.R, boxes[j].S, boxes[j].R)
			}
		}
	}
}
