package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"image/png"
	"net/http"
	"os"
	"strings"
	"time"
)

func main() {
	pngDir := flag.String("png", "", "render mock snapshots into this directory and exit")
	url := flag.String("url", "http://192.168.0.124:8000/api/display", "collector view-model URL")
	refresh := flag.Duration("refresh", 5*time.Second, "fetch period while debugging; 60s after sign-off")
	flag.Parse()
	if *pngDir != "" {
		if err := renderMocks(*pngDir); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	runDevice(*url, *refresh)
}

func renderMocks(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	now := time.Date(2026, 9, 26, 15, 43, 0, 0, time.Local)
	for name, s := range mockSet() {
		a := newApp(now)
		a.CalSaved = true
		a.advance(time.Second)
		a.setSnap(s, nil)
		f, err := os.Create(dir + "/" + name + ".png")
		if err != nil {
			return err
		}
		if err := png.Encode(f, a.Img); err != nil {
			f.Close()
			return err
		}
		f.Close()
		jb, _ := json.MarshalIndent(s, "", "  ")
		if err := os.WriteFile("mock/"+name+".json", jb, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func runDevice(url string, refresh time.Duration) {
	now := time.Now()
	a := newApp(now)
	loadCal(a)
	disp, touch, err := openHardware()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer disp.Close()
	a.ActionURL = actionURL(url)
	a.Post = func(id string) {
		msg := postAction(a.ActionURL, id)
		if id == "wake" && msg == "sent" {
			return
		}
		select {
		case a.Notes <- msg:
		default:
		}
	}
	a.LocalCam = func(on bool) error {
		v := "0"
		if on {
			v = "1"
		}
		resp, err := http.Get("http://127.0.0.1:8080/record?on=" + v)
		if err != nil {
			return err
		}
		resp.Body.Close()
		if resp.StatusCode >= 300 {
			return fmt.Errorf("camera %d", resp.StatusCode)
		}
		return nil
	}
	last := time.Now()
	nextFetch := time.Now()
	var track pressTrack
	failWait := 5 * time.Second
	fetchCh := make(chan fetchResult, 1)
	inFlight := false
	for {
		now = time.Now()
		dt := now.Sub(last)
		if dt < 0 {
			dt = 0
		}
		if dt > 200*time.Millisecond {
			dt = 200 * time.Millisecond
		}
		last = now
		a.Now = now
		a.advance(dt)
		ev, ok := touch.Poll()
		track.apply(a, ev, ok, now)
		select {
		case r := <-fetchCh:
			inFlight = false
			a.setSnap(r.s, r.err)
			nextFetch, failWait = afterFetch(r.started, refresh, failWait, r.s, r.err)
		default:
		}
		if !inFlight && !now.Before(nextFetch) {
			inFlight = true
			started := now
			go func() {
				s, err := fetchSnap(url)
				fetchCh <- fetchResult{s: s, err: err, started: started}
			}()
		}
		// A redraw takes longer than a tap. Samples taken mid-blit are applied
		// after, so paint never runs while the frame buffer is being copied.
		var mid []touchEv
		take := func() {
			ev, ok := touch.Poll()
			if !ok {
				ev = touchEv{}
			}
			mid = append(mid, ev)
		}
		for pass := 0; pass < 2 && a.dirty; pass++ {
			from := len(mid)
			disp.Blit(a.Img, take)
			a.dirty = false
			for _, ev := range mid[from:] {
				track.apply(a, ev, ev.Down, now)
			}
		}
		if track.wasDown {
			time.Sleep(16 * time.Millisecond)
		} else {
			time.Sleep(40 * time.Millisecond)
		}
	}
}

type fetchResult struct {
	s       *Snapshot
	err     error
	started time.Time
}

type pressTrack struct {
	wasDown bool
	downAt  time.Time
	lx, ly  int
}

func (p *pressTrack) apply(a *App, ev touchEv, ok bool, now time.Time) {
	if ok && ev.Down {
		p.lx, p.ly = ev.X, ev.Y
		a.LastRaw = [2]int{ev.RawX, ev.RawY}
		if !p.wasDown {
			a.pointerDown(ev.X, ev.Y)
			p.downAt = now
		}
		p.wasDown = true
		return
	}
	if !p.wasDown {
		return
	}
	p.wasDown = false
	if a.Screen == scrHome && now.Sub(p.downAt) >= 3*time.Second && a.hit(p.lx, p.ly) == "clock" {
		a.holdClock(3 * time.Second)
		saveCal(a)
		return
	}
	a.pointerUp(p.lx, p.ly)
}

func afterFetch(started time.Time, refresh, failWait time.Duration, s *Snapshot, err error) (time.Time, time.Duration) {
	if err != nil || s == nil {
		wait := failWait
		switch {
		case failWait < 10*time.Second:
			failWait = 10 * time.Second
		case failWait < 20*time.Second:
			failWait = 20 * time.Second
		default:
			failWait = 30 * time.Second
		}
		return started.Add(wait), failWait
	}
	failWait = 5 * time.Second
	wait := refresh
	if s.NextInS > 0 && s.NextInS < 120 {
		wait = time.Duration(s.NextInS) * time.Second
	}
	return started.Add(wait), failWait
}

func actionURL(displayURL string) string {
	u := strings.TrimRight(displayURL, "/")
	if i := strings.LastIndex(u, "/api/display"); i >= 0 {
		u = u[:i]
	}
	return u + "/api/actions"
}

func postAction(url, id string) string {
	body := bytes.NewBufferString(`{"id":"` + id + `"}`)
	c := http.Client{Timeout: 5 * time.Second}
	resp, err := c.Post(url, "application/json", body)
	if err != nil {
		return "failed"
	}
	defer resp.Body.Close()
	if resp.StatusCode == 403 {
		return "denied"
	}
	if resp.StatusCode >= 300 {
		return "failed"
	}
	return "sent"
}

func fetchSnap(url string) (*Snapshot, error) {
	c := http.Client{Timeout: 8 * time.Second}
	resp, err := c.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("http %d", resp.StatusCode)
	}
	var s Snapshot
	if err := json.NewDecoder(resp.Body).Decode(&s); err != nil {
		return nil, err
	}
	if s.Schema > schemaKnown {
		return nil, fmt.Errorf("update display")
	}
	return &s, nil
}
