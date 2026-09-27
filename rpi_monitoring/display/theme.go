package main

import "image/color"

func scale(c color.RGBA, num, den uint8) color.RGBA {
	return color.RGBA{
		R: uint8(uint16(c.R) * uint16(num) / uint16(den)),
		G: uint8(uint16(c.G) * uint16(num) / uint16(den)),
		B: uint8(uint16(c.B) * uint16(num) / uint16(den)),
		A: 255,
	}
}

func dayFill(state string) color.RGBA {
	var c color.RGBA
	switch state {
	case "ok":
		c = color.RGBA{0x15, 0x80, 0x3D, 255}
	case "warn":
		c = color.RGBA{0xB4, 0x53, 0x09, 255}
	case "crit":
		c = color.RGBA{0xB9, 0x1C, 0x1C, 255}
	case "busy":
		c = color.RGBA{0x1D, 0x4E, 0xD8, 255}
	case "idle":
		c = color.RGBA{0x1F, 0x29, 0x37, 255}
	default: // off, stale, grey
		c = color.RGBA{0x4B, 0x55, 0x63, 255}
	}
	return scale(c, 7, 8)
}

func nightInk() color.RGBA {
	return color.RGBA{0x40, 0x10, 0x10, 255} // ~1/8 of a red
}
