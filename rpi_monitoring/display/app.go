package main

import (
	"fmt"
	"image"
	"image/color"
	"time"
)

const (
	scrBoot       = "boot"
	scrConnecting = "connecting"
	scrHome       = "home"
	scrDetail     = "detail"
	scrCamera     = "camera"
	scrConfirm    = "confirm"
	scrNight      = "night"
	scrBang       = "bang"
	scrCalib      = "calib"
	scrGrey       = "grey"

	bootGrace   = 2 * time.Minute
	idleBack    = 5 * time.Second
	nightWake   = 60 * time.Second
	calibAbort  = 15 * time.Second
	missesBang  = 6
	schemaKnown = 1
)

type App struct {
	F      *faces
	Img    *image.RGBA
	Snap   *Snapshot
	Screen string
	Tile   int
	Page   int
	Night  bool

	Now  time.Time
	Mono time.Duration

	Started    time.Duration
	IdleAt     time.Duration
	Fails      int
	LastOK     time.Duration
	WakeUntil  time.Duration
	Toast      string
	ToastUntil time.Duration
	Flash      int
	Press      image.Point
	Down       bool
	Target     string

	CalSaved bool
	CalStep  int
	CalRaw   [4][2]int
	LastRaw  [2]int
	CalPts   [4][2]int

	Action   *Action
	ArmedAt  time.Duration
	LocalCam func(on bool) error

	NightFrom, NightTo int
	ThemeNight         bool
	Locked             bool
	RecBase            int
	RecAt              time.Duration
	view               string
	boxes              []inkBox
}

func newApp(now time.Time) *App {
	a := &App{
		F:         loadFaces(),
		Img:       image.NewRGBA(image.Rect(0, 0, W, H)),
		Screen:    scrBoot,
		Now:       now,
		NightFrom: 23,
		NightTo:   7,
	}
	a.paint()
	return a
}

func (a *App) advance(dt time.Duration) {
	a.Mono += dt
	a.Now = a.Now.Add(dt)
	if a.Screen == scrBoot {
		a.Screen = scrConnecting
		if !a.CalSaved {
			a.Screen = scrCalib
			a.CalStep = 0
		}
		a.Started = a.Mono
		a.IdleAt = a.Mono
	}
	a.ThemeNight = a.inNight() && a.Mono > a.WakeUntil
	if a.ThemeNight && a.Screen == scrHome && !a.Locked {
		a.Screen = scrNight
	}
	if a.Toast != "" && a.Mono > a.ToastUntil {
		a.Toast = ""
	}
	idle := a.Mono - a.IdleAt
	switch a.Screen {
	case scrDetail, scrCamera, scrConfirm, scrGrey:
		if !a.Locked && idle >= idleBack {
			a.goHome()
		}
	case scrCalib:
		if idle >= calibAbort && a.CalSaved {
			a.goHome()
		}
	}
	sig := a.viewSig()
	if sig != a.view {
		a.view = sig
		a.paint()
	}
}

func (a *App) viewSig() string {
	ts := ""
	if a.Snap != nil {
		ts = a.Snap.TS
	}
	tick := ""
	if a.Screen == scrCamera {
		tick = fmt.Sprint(a.camElapsed())
	}
	return fmt.Sprintf("%s|%d|%d|%s|%v|%v|%v|%s|%s|%d|%v|%s",
		a.Screen, a.Tile, a.Page, a.Toast, a.Down, a.ThemeNight, a.Locked,
		a.Now.Format("15:04"), ts, a.CalStep, a.Press, tick)
}

func (a *App) inNight() bool {
	h := a.Now.Hour()
	if a.NightFrom > a.NightTo {
		return h >= a.NightFrom || h < a.NightTo
	}
	return h >= a.NightFrom && h < a.NightTo
}

func (a *App) goHome() {
	a.Action = nil
	if a.ThemeNight || (a.inNight() && a.Mono > a.WakeUntil) {
		a.Screen = scrNight
	} else {
		a.Screen = scrHome
	}
	a.IdleAt = a.Mono
}

func (a *App) setSnap(s *Snapshot, err error) {
	if err != nil || s == nil {
		a.Fails++
		if a.Fails >= missesBang && a.Mono-a.Started >= bootGrace {
			if a.Screen != scrCamera && a.Screen != scrCalib {
				a.Screen = scrBang
			}
		}
		a.paint()
		return
	}
	a.Fails = 0
	a.Snap = s
	a.LastOK = a.Mono
	if a.Screen == scrConnecting || a.Screen == scrBang || a.Screen == scrBoot || a.Screen == scrGrey {
		a.goHome()
	}
	a.noteAlerts()
	a.noteRec()
	a.paint()
}

func (a *App) noteRec() {
	if a.Snap == nil {
		return
	}
	for i := range a.Snap.Tiles {
		c := a.Snap.Tiles[i].Camera
		if c != nil && c.Recording {
			a.RecBase = c.ElapsedS
			a.RecAt = a.Mono
			return
		}
	}
}

func (a *App) camElapsed() int {
	t := a.cur()
	if t == nil || t.Camera == nil || !t.Camera.Recording {
		return 0
	}
	el := t.Camera.ElapsedS
	if a.RecAt > 0 {
		extra := int((a.Mono - a.RecAt) / time.Second)
		if extra > 0 {
			el = a.RecBase + extra
		}
	}
	return el
}

func (a *App) noteAlerts() {
	if a.Snap == nil {
		return
	}
	if a.Snap.Summary.Crit > 0 && a.Screen == scrNight {
		a.WakeUntil = a.Mono + nightWake
		a.Screen = scrHome
		a.Flash = 3
	}
}

func (a *App) pointerDown(x, y int) {
	a.Down = true
	a.Press = image.Pt(x, y)
	a.Target = a.hit(x, y)
	a.IdleAt = a.Mono
	a.paint()
}

func (a *App) pointerUp(x, y int) {
	id := a.hit(x, y)
	if a.Target == "lock" && rectDist(lockHit(), x, y) <= 36 {
		id = "lock"
	}
	same := a.Down && id != "" && id == a.Target
	a.Down = false
	a.Target = ""
	if !same {
		a.paint()
		return
	}
	a.tap(id)
	a.paint()
}

func (a *App) tap(id string) {
	a.IdleAt = a.Mono
	if id == "lock" {
		a.Locked = !a.Locked
		if a.Locked {
			a.toast("locked")
		} else {
			a.toast("open")
		}
		return
	}
	if a.inNight() && a.Screen == scrNight {
		a.WakeUntil = a.Mono + nightWake
		a.ThemeNight = false
		a.Screen = scrHome
		return
	}
	switch a.Screen {
	case scrBang:
		a.Screen = scrGrey
	case scrCalib:
		a.calibTap(id)
	case scrHome, scrGrey:
		a.homeTap(id)
	case scrDetail:
		a.detailTap(id)
	case scrCamera:
		a.cameraTap(id)
	case scrConfirm:
		a.confirmTap(id)
	}
}

func (a *App) homeTap(id string) {
	if id == "summary" && a.Snap != nil && a.Snap.Summary.Worst != "" {
		if i := a.tileIndex(a.Snap.Summary.Worst); i >= 0 {
			a.openTile(i)
		}
		return
	}
	if id == "clock" {
		return
	}
	if len(id) > 5 && id[:5] == "tile:" {
		var i int
		for _, c := range id[5:] {
			i = i*10 + int(c-'0')
		}
		a.openTile(i)
	}
}

func (a *App) openTile(i int) {
	if a.Snap == nil || i < 0 || i >= len(a.Snap.Tiles) {
		return
	}
	a.Tile = i
	a.Page = 0
	t := a.Snap.Tiles[i]
	if t.Screen == "camera" || t.Camera != nil && t.ID == "camera" {
		a.Screen = scrCamera
		return
	}
	a.Screen = scrDetail
}

func (a *App) tileIndex(id string) int {
	if a.Snap == nil {
		return -1
	}
	for i, t := range a.Snap.Tiles {
		if t.ID == id {
			return i
		}
	}
	return -1
}

func (a *App) cur() *Tile {
	if a.Snap == nil || a.Tile < 0 || a.Tile >= len(a.Snap.Tiles) {
		return nil
	}
	return &a.Snap.Tiles[a.Tile]
}

func (a *App) detailTap(id string) {
	t := a.cur()
	if t == nil {
		a.goHome()
		return
	}
	switch id {
	case "back":
		a.goHome()
	case "page":
		if len(t.Pages) > 1 {
			a.Page = (a.Page + 1) % len(t.Pages)
		}
	default:
		if len(id) > 4 && id[:4] == "act:" {
			a.startAction(id[4:])
		}
	}
}

func (a *App) startAction(id string) {
	t := a.cur()
	if t == nil || a.Page >= len(t.Pages) {
		return
	}
	for i := range t.Pages[a.Page].Actions {
		act := &t.Pages[a.Page].Actions[i]
		if act.ID != id {
			continue
		}
		if !act.Enabled {
			a.toast(act.Why)
			return
		}
		if act.Confirm != nil {
			cp := *act
			a.Action = &cp
			a.Screen = scrConfirm
			a.ArmedAt = a.Mono + 700*time.Millisecond
			return
		}
		a.toast("Sending...")
	}
}

func (a *App) confirmTap(id string) {
	switch id {
	case "cancel":
		a.Action = nil
		a.Screen = scrDetail
	case "ok":
		if a.Mono < a.ArmedAt {
			return
		}
		a.toast("Sending...")
		a.Action = nil
		a.Screen = scrDetail
	}
}

func (a *App) cameraTap(id string) {
	cam := a.cur()
	switch id {
	case "back":
		a.goHome()
	case "start":
		if a.LocalCam != nil {
			if err := a.LocalCam(true); err != nil {
				a.toast(err.Error())
				return
			}
		}
		if cam != nil && cam.Camera != nil {
			cam.Camera.Recording = true
			cam.Camera.Phase = "recording"
			cam.Camera.ElapsedS = 0
			cam.State = "crit"
		}
		a.RecBase = 0
		a.RecAt = a.Mono
		a.toast("Starting...")
	case "stop":
		if a.LocalCam != nil {
			_ = a.LocalCam(false)
		}
		if cam != nil && cam.Camera != nil {
			cam.Camera.Recording = false
			cam.Camera.Phase = "saved"
			cam.State = "idle"
		}
		a.toast("clip saved")
	}
}

func (a *App) calibTap(id string) {
	if id != "cross" {
		return
	}
	if a.CalStep < 4 {
		a.CalRaw[a.CalStep] = a.LastRaw
		a.CalStep++
		if a.CalStep == 4 && a.LastRaw != [2]int{} {
			hwCal = calFromPoints(a.CalRaw)
		}
		a.IdleAt = a.Mono
		return
	}
	x, y := mapCal(a.LastRaw[0], a.LastRaw[1], hwCal)
	if a.LastRaw != [2]int{} && (absInt(x-W/2) > 60 || absInt(y-H/2) > 60) {
		a.CalStep = 0
		a.toast("again")
		return
	}
	a.CalSaved = true
	saveCal(a)
	a.goHome()
}

func (a *App) toast(s string) {
	if s == "" {
		s = "ok"
	}
	a.Toast = s
	a.ToastUntil = a.Mono + 3*time.Second
}

func (a *App) holdClock(d time.Duration) {
	if a.Screen == scrHome && d >= 3*time.Second {
		a.Screen = scrCalib
		a.CalStep = 0
		a.IdleAt = a.Mono
		a.paint()
	}
}

func (a *App) ink() color.RGBA {
	if a.nightLook() {
		return nightInk()
	}
	return color.RGBA{255, 255, 255, 255}
}

func (a *App) nightLook() bool {
	switch a.Screen {
	case scrBang, scrConnecting, scrBoot, scrCalib:
		return false
	}
	return a.inNight()
}

func (a *App) bg() color.RGBA {
	if a.Screen == scrBang {
		return dayFill("crit")
	}
	return color.RGBA{0, 0, 0, 255}
}
