package main

import (
	"fmt"
	"image"
	"image/color"
	"strings"
	"time"

	"golang.org/x/image/font"
	"golang.org/x/image/math/fixed"
)

func (a *App) put(face font.Face, s string, r image.Rectangle, c color.Color, center bool) {
	if face == nil || s == "" || r.Dx() < 2 || r.Dy() < 2 {
		return
	}
	shown := fitPx(face, s, r.Dx())
	if shown == "" {
		return
	}
	a.boxes = append(a.boxes, inkBox{R: r, S: shown, F: face})
	sub, ok := a.Img.SubImage(r).(*image.RGBA)
	if !ok {
		return
	}
	m := face.Metrics()
	w := font.MeasureString(face, shown).Ceil()
	x := r.Min.X
	if center {
		x = r.Min.X + (r.Dx()-w)/2
	}
	if x < r.Min.X {
		x = r.Min.X
	}
	lineH := m.Ascent.Ceil() + m.Descent.Ceil()
	y := r.Min.Y + m.Ascent.Ceil()
	if r.Dy() > lineH {
		y = r.Min.Y + (r.Dy()-lineH)/2 + m.Ascent.Ceil()
	}
	d := font.Drawer{Dst: sub, Src: &image.Uniform{c}, Face: face, Dot: fixed.P(x, y)}
	d.DrawString(shown)
}

func (a *App) fitFace(s string, maxW int, faces ...font.Face) font.Face {
	for _, f := range faces {
		if f != nil && font.MeasureString(f, s).Ceil() <= maxW {
			return f
		}
	}
	return faces[len(faces)-1]
}

func (a *App) paint() {
	a.boxes = nil
	fill(a.Img, a.Img.Bounds(), a.bg())
	ink := a.ink()
	switch a.Screen {
	case scrBoot:
		a.stackCenter(ink, 70, []stackLine{{a.F.sans22, "lcd-monitor"}, {a.F.sans14, "dante-pi"}})
	case scrConnecting:
		grey := color.RGBA{120, 120, 120, 255}
		a.stackCenter(grey, 80, []stackLine{{a.F.sans22, "link"}})
	case scrBang:
		white := color.RGBA{255, 255, 255, 255}
		lines := []stackLine{{a.F.mono48, "!"}, {a.F.sans22, "no link"}}
		a.stackCenter(white, 36, lines)
	case scrNight:
		a.put(a.F.mono48, a.Now.Format("15:04"), image.Rect(8, 70, W-8, 170), nightInk(), true)
		if a.recording() {
			a.put(a.F.sans11, "REC", image.Rect(W-52, 8, W-8, 8+faceH(a.F.sans11)), nightInk(), true)
		}
	case scrCalib:
		a.paintCalib(ink)
	case scrHome, scrGrey:
		a.paintHome(ink)
	case scrDetail:
		a.paintDetail(ink, false)
	case scrConfirm:
		a.paintDetail(ink, true)
		a.paintConfirm()
	case scrCamera:
		a.paintCamera(ink)
	}
	if a.Toast != "" && a.Screen != scrBang && a.Screen != scrNight {
		a.paintToast()
	}
}

type stackLine struct {
	face font.Face
	text string
}

func (a *App) stackCenter(c color.Color, y int, lines []stackLine) {
	for _, ln := range lines {
		h := faceH(ln.face) + 4
		a.put(ln.face, ln.text, image.Rect(8, y, W-8, y+h), c, true)
		y += h
	}
}

func (a *App) recording() bool {
	if a.Snap == nil {
		return false
	}
	for _, t := range a.Snap.Tiles {
		if t.Camera != nil && t.Camera.Recording {
			return true
		}
	}
	return false
}

func (a *App) paintHome(ink color.Color) {
	fill(a.Img, image.Rect(0, 0, W, statusH), color.RGBA{0, 0, 0, 255})
	if a.Toast != "" {
		r := image.Rect(4, 0, W-4, statusH)
		if a.recording() {
			r.Max.X = recRect().Min.X - 4
		}
		a.put(a.F.sans14, a.Toast, r, ink, true)
	} else {
		a.put(a.F.sans14, a.Now.Format("15:04"), clockRect(), ink, false)
		sum, sumCol := a.statusLine()
		a.put(a.F.sans14, sum, statusSummaryRect(), sumCol, true)
	}
	if a.recording() {
		a.put(a.F.sans14, "REC", recRect(), color.RGBA{255, 80, 80, 255}, true)
	}
	if a.Toast == "" && a.Snap != nil && a.Snap.TempOut != "" {
		tc := ink
		if a.nightLook() {
			tc = nightInk()
		}
		a.put(a.F.sans14, a.Snap.TempOut, outTempRect(), tc, true)
	}
	if a.Snap == nil {
		return
	}
	white := color.RGBA{255, 255, 255, 255}
	for i, t := range a.Snap.Tiles {
		if i >= 8 {
			break
		}
		r := tileRect(i)
		col := dayFill(t.State)
		if a.nightLook() || a.Screen == scrGrey {
			col = color.RGBA{20, 20, 20, 255}
		}
		pressed := a.Down && a.Target == fmt.Sprintf("tile:%d", i)
		if pressed {
			col = color.RGBA{255, 255, 255, 255}
		}
		fill(a.Img, r, col)
		fg := white
		if a.nightLook() || a.Screen == scrGrey {
			fg = nightInk()
			if a.Screen == scrGrey {
				fg = color.RGBA{160, 160, 160, 255}
			}
		}
		if pressed {
			fg = color.RGBA{0, 0, 0, 255}
		}
		a.paintTile(r, t, fg)
	}
}

func (a *App) paintLock() {
	r := lockRect()
	fill(a.Img, r, color.RGBA{0, 0, 0, 255})
	ink := color.RGBA{220, 220, 220, 255}
	if a.Locked {
		ink = color.RGBA{250, 204, 21, 255}
	}
	drawLock(a.Img, r, ink, a.Locked)
}

func drawLock(dst *image.RGBA, r image.Rectangle, c color.Color, closed bool) {
	body := image.Rect(r.Min.X+9, r.Min.Y+18, r.Max.X-9, r.Max.Y-6)
	fill(dst, body, c)
	left, right := r.Min.X+11, r.Max.X-12
	top, neck := r.Min.Y+7, r.Min.Y+18
	for i := 0; i < 3; i++ {
		line(dst, image.Pt(left+i, top), image.Pt(left+i, neck), c)
		line(dst, image.Pt(left, top+i), image.Pt(right, top+i), c)
		if closed {
			line(dst, image.Pt(right-i, top), image.Pt(right-i, neck), c)
		} else {
			line(dst, image.Pt(right-i, top), image.Pt(right-i, top+8), c)
		}
	}
	if closed {
		fill(dst, image.Rect(r.Min.X+16, r.Min.Y+22, r.Min.X+20, r.Min.Y+28), color.RGBA{0, 0, 0, 255})
	}
}

func metricInk(state string) color.Color {
	switch state {
	case "warn":
		return color.RGBA{251, 191, 36, 255}
	case "crit":
		return color.RGBA{248, 113, 113, 255}
	case "off", "stale":
		return color.RGBA{156, 163, 175, 255}
	case "busy":
		return color.RGBA{96, 165, 250, 255}
	default:
		return color.RGBA{74, 222, 128, 255}
	}
}

func (a *App) paintTile(r image.Rectangle, t Tile, fg color.Color) {
	const pad = 4
	x0, x1 := r.Min.X+pad, r.Max.X-pad
	nameH := faceH(a.F.sans14) + 2
	capH := faceH(a.F.sans14) + 2
	a.put(a.F.sans14, shortName(t.Label), image.Rect(x0, r.Min.Y+3, x1, r.Min.Y+3+nameH), fg, true)
	big := shortNum(t.Big)
	face := a.fitFace(big, x1-x0, a.F.mono32, a.F.mono24, a.F.sans22)
	top := r.Min.Y + 3 + nameH
	bot := r.Max.Y - 3 - capH
	a.put(face, big, image.Rect(x0, top, x1, bot), fg, true)
	a.put(a.F.sans14, tileCap(t), image.Rect(x0, r.Max.Y-3-capH, x1, r.Max.Y-3), fg, true)
}

func (a *App) statusLine() (string, color.Color) {
	grey := color.RGBA{156, 163, 175, 255}
	if a.Screen == scrGrey || a.Snap == nil {
		return "none", grey
	}
	if a.LastOK > 0 && a.Mono-a.LastOK >= staleAfter {
		m := int((a.Mono - a.LastOK) / time.Minute)
		if m < 1 {
			m = 1
		}
		return fmt.Sprintf("old %dm", m), grey
	}
	if a.Snap.Summary.Crit > 0 {
		return fmt.Sprintf("%d bad", a.Snap.Summary.Crit), color.RGBA{248, 113, 113, 255}
	}
	if a.Snap.Summary.Warn > 0 {
		return fmt.Sprintf("%d warn", a.Snap.Summary.Warn), color.RGBA{251, 191, 36, 255}
	}
	return "all ok", color.RGBA{74, 222, 128, 255}
}

func (a *App) paintDetail(ink color.Color, headerOnly bool) {
	t := a.cur()
	fill(a.Img, image.Rect(0, 0, W, headerH), dayFill("off"))
	if t != nil && !a.nightLook() {
		fill(a.Img, image.Rect(0, 0, W, headerH), dayFill(t.State))
	}
	white := color.RGBA{255, 255, 255, 255}
	a.put(a.F.sans22, "<", backRect(), white, true)
	title := "detail"
	pages := 1
	if t != nil {
		title = shortName(t.Label)
		if len(t.Pages) > 0 {
			pages = len(t.Pages)
		}
	}
	a.put(a.F.sans22, title, titleRect(), white, true)
	a.put(a.F.sans20, fmt.Sprintf("%d/%d", a.Page+1, pages), pageRect(), white, true)
	if !headerOnly {
		a.paintLock()
	}
	if headerOnly || t == nil || a.Page >= len(t.Pages) {
		return
	}
	p := t.Pages[a.Page]
	rows := append([]Row{}, p.Rows...)
	if t.ID == "pi" {
		val, st := "none", "crit"
		if a.CamOK {
			val, st = "ok", "ok"
		}
		rows = append(rows, Row{Label: "cam", Value: val, State: st})
	}
	dual := false
	for _, row := range rows {
		if row.Value2 != "" {
			dual = true
			break
		}
	}
	face := a.F.sans20
	pitch := faceH(face) + 1
	if len(rows) >= 9 {
		face = a.F.sans17
		pitch = 22
	}
	right := W - 8
	btns := actionButtons(len(p.Actions))
	if len(btns) > 0 {
		right = btns[0].Min.X - 6
	}
	y := headerH + 2
	if dual {
		hh := faceH(a.F.sans11)
		a.put(a.F.sans11, "now", image.Rect(dualNowX0, y, dualNowX1, y+hh), white, false)
		a.put(a.F.sans11, "prev", image.Rect(dualPrevX0, y, right, y+hh), white, false)
		y += hh + 1
	}
	n := 0
	for _, row := range rows {
		if n >= 9 || y >= H-2 {
			break
		}
		a.paintMetricRow(face, row, y, pitch, right, dual)
		y += pitch
		n++
	}
	if n == 0 {
		a.put(a.F.mono32, shortNum(t.Big), image.Rect(12, headerH+16, W-12, headerH+80), white, true)
	}
	for i, act := range p.Actions {
		if i >= len(btns) {
			break
		}
		a.paintAction(btns[i], act)
	}
}

func (a *App) paintMetricRow(face font.Face, row Row, y, pitch, right int, dual bool) {
	x1 := right
	lock := lockRect()
	if y < lock.Max.Y && y+pitch > lock.Min.Y && x1 > lock.Min.X-4 {
		x1 = lock.Min.X - 4
	}
	white := color.RGBA{255, 255, 255, 255}
	if !dual {
		a.put(face, row.Label, image.Rect(8, y, 118, y+pitch), white, false)
		a.put(face, row.Value, image.Rect(122, y, x1, y+pitch), metricInk(row.State), false)
		return
	}
	a.put(face, row.Label, image.Rect(8, y, dualLabelX1, y+pitch), white, false)
	a.put(face, row.Value, image.Rect(dualNowX0, y, dualNowX1, y+pitch), metricInk(row.State), false)
	if row.Value2 != "" && dualPrevX0 < x1 {
		a.put(face, row.Value2, image.Rect(dualPrevX0, y, x1, y+pitch), metricInk(row.State2), false)
	}
}

func (a *App) paintAction(r image.Rectangle, act Action) {
	c := dayFill("ok")
	if !act.Enabled {
		c = dayFill("off")
	}
	fill(a.Img, r, c)
	white := color.RGBA{255, 255, 255, 255}
	lines := buttonLines(act.Label)
	if len(lines) <= 1 {
		label := ""
		if len(lines) == 1 {
			label = lines[0]
		}
		a.put(a.F.sans20, label, r.Inset(4), white, true)
		return
	}
	h := faceH(a.F.sans20)
	total := h*2 + 2
	y := r.Min.Y + (r.Dy()-total)/2
	if y < r.Min.Y {
		y = r.Min.Y
	}
	a.put(a.F.sans20, lines[0], image.Rect(r.Min.X+4, y, r.Max.X-4, y+h), white, true)
	y += h + 2
	a.put(a.F.sans20, lines[1], image.Rect(r.Min.X+4, y, r.Max.X-4, y+h), white, true)
}

func buttonLines(label string) []string {
	f := strings.Fields(label)
	if len(f) <= 1 {
		return f
	}
	return []string{f[0], strings.Join(f[1:], " ")}
}

func (a *App) paintConfirm() {
	panel := confirmPanel()
	fill(a.Img, panel, color.RGBA{12, 12, 12, 255})
	a.dropBoxes(panel)
	title, verb := "Sure?", "OK"
	if a.Action != nil && a.Action.Confirm != nil {
		title = shortTitle(a.Action.Confirm.Title)
		if a.Action.Confirm.Verb != "" {
			verb = shortWord(a.Action.Confirm.Verb)
		}
	}
	white := color.RGBA{255, 255, 255, 255}
	y := panel.Min.Y + 28
	th := faceH(a.F.sans22) + 8
	a.put(a.F.sans22, title, image.Rect(panel.Min.X+8, y, panel.Max.X-8, y+th), white, true)
	cancel, okb := confirmButtons()
	fill(a.Img, cancel, dayFill("off"))
	oc := dayFill("ok")
	if a.Mono < a.ArmedAt {
		oc = dayFill("off")
	}
	fill(a.Img, okb, oc)
	a.put(a.F.sans22, "No", cancel.Inset(4), white, true)
	a.put(a.F.sans22, verb, okb.Inset(4), white, true)
}

func (a *App) dropBoxes(cover image.Rectangle) {
	kept := a.boxes[:0]
	for _, b := range a.boxes {
		if b.R.Intersect(cover).Empty() {
			kept = append(kept, b)
		}
	}
	a.boxes = kept
}

func (a *App) paintToast() {
	if a.Screen == scrHome || a.Screen == scrGrey {
		return
	}
	r := titleRect()
	fill(a.Img, r, color.RGBA{0, 0, 0, 255})
	a.dropBoxes(r)
	a.put(a.F.sans14, shortWord(a.Toast), r, color.RGBA{255, 255, 255, 255}, true)
}

func (a *App) paintCamera(ink color.Color) {
	fill(a.Img, image.Rect(0, 0, W, headerH), color.RGBA{0, 0, 0, 255})
	a.put(a.F.sans22, "<", backRect(), ink, true)
	a.put(a.F.sans22, "CAM", titleRect(), ink, true)
	a.paintLock()
	cam := &Camera{Phase: "idle", MaxS: 1800, Note: "live view pauses while recording"}
	if t := a.cur(); t != nil && t.Camera != nil {
		cam = t.Camera
	}
	phase := cam.Phase
	if phase == "" {
		if cam.Recording {
			phase = "recording"
		} else {
			phase = "idle"
		}
	}
	el := a.camElapsed()
	mm, ss := el/60, el%60
	a.put(a.F.mono48, fmt.Sprintf("%02d:%02d", mm, ss), image.Rect(8, headerH+6, W-8, headerH+78), ink, true)
	btn := cameraButton()
	label := "START"
	bc := dayFill("ok")
	if phase == "recording" || phase == "starting" {
		label = "STOP"
		bc = dayFill("crit")
	}
	fill(a.Img, btn, bc)
	a.put(a.F.sans28, label, btn.Inset(4), color.RGBA{255, 255, 255, 255}, true)
}

func (a *App) paintCalib(ink color.Color) {
	if a.CalStep != 4 {
		a.put(a.F.sans22, "tap", image.Rect(90, 100, W-90, 136), ink, true)
	}
	pts := []image.Point{{20, 20}, {W - 20, 20}, {20, H - 20}, {W - 20, H - 20}, {W / 2, H / 2}}
	if a.CalStep >= len(pts) {
		return
	}
	p := pts[a.CalStep]
	line(a.Img, image.Pt(p.X-8, p.Y), image.Pt(p.X+8, p.Y), ink)
	line(a.Img, image.Pt(p.X, p.Y-8), image.Pt(p.X, p.Y+8), ink)
}

func (a *App) hit(x, y int) string {
	p := image.Pt(x, y)
	switch a.Screen {
	case scrCalib:
		return "cross"
	case scrBang:
		return "bang"
	case scrNight:
		return "night"
	case scrConfirm:
		cancel, okb := confirmButtons()
		if p.In(cancel) {
			return "cancel"
		}
		if p.In(okb) {
			return "ok"
		}
		return ""
	case scrCamera:
		if p.In(lockHit()) {
			return "lock"
		}
		if p.In(image.Rect(0, 0, 90, headerH)) {
			return "back"
		}
		if p.In(cameraButton()) {
			if t := a.cur(); t != nil && t.Camera != nil && t.Camera.Recording {
				return "stop"
			}
			return "start"
		}
	case scrDetail:
		if t := a.cur(); t != nil && a.Page < len(t.Pages) {
			acts := t.Pages[a.Page].Actions
			btns := actionButtons(len(acts))
			for i, act := range acts {
				if i >= len(btns) {
					break
				}
				if p.In(btns[i]) {
					return "act:" + act.ID
				}
			}
		}
		if p.In(lockHit()) {
			return "lock"
		}
		if p.In(image.Rect(0, 0, 90, headerH)) {
			return "back"
		}
		if p.In(image.Rect(W-80, 0, W, headerH)) {
			return "page"
		}
	case scrHome, scrGrey:
		if p.In(clockRect()) {
			return "clock"
		}
		if p.In(statusSummaryRect()) {
			return "summary"
		}
		if a.Snap != nil {
			n := len(a.Snap.Tiles)
			if n > 8 {
				n = 8
			}
			if i := nearestTile(x, y, n); i >= 0 {
				return fmt.Sprintf("tile:%d", i)
			}
		}
	}
	return ""
}

func shortName(s string) string {
	switch strings.ToUpper(strings.TrimSpace(s)) {
	case "RACOON":
		return "RAC"
	case "WORKER":
		return "WRK"
	case "EATERIA":
		return "EAT"
	case "BACKUP":
		return "BAK"
	case "NETWORK":
		return "NET"
	case "CAMERA":
		return "CAM"
	default:
		return shortWord(s)
	}
}

func shortWord(s string) string {
	s = strings.Trim(strings.TrimSpace(s), ".!?")
	if s == "" {
		return ""
	}
	if i := strings.IndexAny(s, " \t"); i > 0 {
		s = s[:i]
	}
	switch strings.ToLower(s) {
	case "starting", "start":
		return "Start"
	case "stopping", "stop":
		return "Stop"
	case "recording":
		return "Rec"
	}
	if rs := []rune(s); len(rs) > 6 {
		return string(rs[:6])
	}
	return s
}

func tileCap(t Tile) string {
	switch t.State {
	case "off":
		return "off"
	case "busy":
		return "busy"
	}
	c := shortWord(t.Cap)
	switch strings.ToLower(c) {
	case "", "since", "last", "wan", "on":
		c = ""
	}
	if c == "" {
		c = shortWord(t.L2)
	}
	switch strings.ToLower(c) {
	case "", "since", "last", "wan", "on":
		if t.State == "warn" || t.State == "crit" {
			return "bad"
		}
		return ""
	}
	return c
}

func shortNum(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexAny(s, " \t"); i > 0 {
		s = s[:i]
	}
	if i := strings.IndexByte(s, '%'); i >= 0 {
		return s[:i+1]
	}
	return s
}

func shortTitle(s string) string {
	s = strings.TrimRight(strings.TrimSpace(s), "?")
	f := strings.Fields(s)
	if len(f) == 0 {
		return "Sure?"
	}
	if len(f) == 1 {
		return f[0] + "?"
	}
	return f[0] + " " + f[1] + "?"
}

func fit(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n <= 1 {
		return ""
	}
	return s[:n-1] + "."
}
