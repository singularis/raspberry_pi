//go:build !pi

package main

import (
	"fmt"
	"image"
)

type panel struct{}

func (panel) Blit(*image.RGBA) {}
func (panel) Close()            {}

type touchEv struct {
	X, Y       int
	RawX, RawY int
	Down       bool
}

type touchDev struct{}

func (touchDev) Poll() (touchEv, bool) { return touchEv{}, false }

func openHardware() (panel, touchDev, error) {
	return panel{}, touchDev{}, fmt.Errorf("display hardware needs -tags pi")
}

func loadCal(a *App) {}
func saveCal(a *App) {}
