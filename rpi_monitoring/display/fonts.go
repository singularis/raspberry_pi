package main

import (
	_ "embed"

	"golang.org/x/image/font/opentype"
)

//go:embed fonts/DejaVuSans-Bold.ttf
var sansTTF []byte

//go:embed fonts/DejaVuSansMono-Bold.ttf
var monoTTF []byte

func mustFont(name string) *opentype.Font {
	b := sansTTF
	if name != "fonts/DejaVuSans-Bold.ttf" {
		b = monoTTF
	}
	f, err := opentype.Parse(b)
	if err != nil {
		panic(err)
	}
	return f
}
