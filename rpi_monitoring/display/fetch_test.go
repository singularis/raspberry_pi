package main

import (
	"fmt"
	"testing"
	"time"
)

func TestAfterFetchBackoff(t *testing.T) {
	start := time.Date(2026, 10, 18, 22, 0, 0, 0, time.UTC)
	next, fail := afterFetch(start, 5*time.Second, 5*time.Second, nil, fmt.Errorf("down"))
	if !next.Equal(start.Add(5*time.Second)) || fail != 10*time.Second {
		t.Fatalf("first fail %s %s", next.Sub(start), fail)
	}
	next, fail = afterFetch(start, 5*time.Second, fail, nil, fmt.Errorf("down"))
	if !next.Equal(start.Add(10*time.Second)) || fail != 20*time.Second {
		t.Fatalf("second fail %s %s", next.Sub(start), fail)
	}
	next, fail = afterFetch(start, 5*time.Second, fail, nil, fmt.Errorf("down"))
	if !next.Equal(start.Add(20*time.Second)) || fail != 30*time.Second {
		t.Fatalf("third fail %s %s", next.Sub(start), fail)
	}
	next, fail = afterFetch(start, 5*time.Second, fail, nil, fmt.Errorf("down"))
	if !next.Equal(start.Add(30*time.Second)) || fail != 30*time.Second {
		t.Fatalf("fourth fail %s %s", next.Sub(start), fail)
	}
	next, fail = afterFetch(start, 5*time.Second, 30*time.Second, &Snapshot{NextInS: 58}, nil)
	if !next.Equal(start.Add(58*time.Second)) || fail != 5*time.Second {
		t.Fatalf("ok %s %s", next.Sub(start), fail)
	}
}

func TestPressTrackTapAndHold(t *testing.T) {
	now := time.Date(2026, 9, 26, 15, 43, 0, 0, time.UTC)
	a := boot(t, now, baseSnap())
	var p pressTrack
	p.apply(a, touchEv{X: 30, Y: 40, Down: true}, true, now)
	if a.Screen == scrSettings || a.Screen == scrCalib {
		t.Fatalf("finger down already left home for %s", a.Screen)
	}
	p.apply(a, touchEv{X: 32, Y: 42, Down: true}, true, now.Add(time.Second))
	p.apply(a, touchEv{}, false, now.Add(time.Second))
	if p.wasDown || a.Screen != scrSettings {
		t.Fatalf("short tap screen %s down %v", a.Screen, p.wasDown)
	}

	a = boot(t, now, baseSnap())
	p = pressTrack{}
	p.apply(a, touchEv{X: 30, Y: 40, Down: true}, true, now)
	p.apply(a, touchEv{}, false, now.Add(3*time.Second))
	if a.Screen != scrCalib {
		t.Fatalf("clock hold screen %s", a.Screen)
	}
}
