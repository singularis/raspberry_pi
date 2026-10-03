package main

import "encoding/json"

// View model from the collector. The Pi draws this and does not interpret metrics.

type Snapshot struct {
	Schema   int    `json:"schema"`
	TS       string `json:"ts"`
	NextInS  int    `json:"next_in_s"`
	TempOut  string `json:"temp_out,omitempty"`
	Humidity string `json:"humidity,omitempty"`
	Pressure string `json:"pressure,omitempty"`
	Summary  struct {
		Warn  int    `json:"warn"`
		Crit  int    `json:"crit"`
		Worst string `json:"worst"`
	} `json:"summary"`
	Tiles []Tile `json:"tiles"`
}

type Tile struct {
	ID     string    `json:"id"`
	Label  string    `json:"label"`
	State  string    `json:"state"`
	AgeS   int       `json:"age_s"`
	Big    string    `json:"big"`
	Cap    string    `json:"cap"`
	L2     string    `json:"l2"`
	L3     string    `json:"l3"`
	Spark  []float64 `json:"spark,omitempty"`
	Pages  []Page    `json:"pages,omitempty"`
	Screen string    `json:"screen,omitempty"`
	Camera *Camera   `json:"camera,omitempty"`
}

type Page struct {
	Chart   *Chart   `json:"chart,omitempty"`
	Rows    []Row    `json:"rows,omitempty"`
	Bars    []Bar    `json:"bars,omitempty"`
	List    []string `json:"list,omitempty"`
	Actions []Action `json:"actions,omitempty"`
}

type Row struct {
	Label  string
	Value  string
	State  string
	Value2 string
	State2 string
}

func (r *Row) UnmarshalJSON(data []byte) error {
	var arr []string
	if err := json.Unmarshal(data, &arr); err != nil {
		return err
	}
	if len(arr) > 0 {
		r.Label = arr[0]
	}
	if len(arr) > 1 {
		r.Value = arr[1]
	}
	if len(arr) > 2 {
		r.State = arr[2]
	}
	if len(arr) > 3 {
		r.Value2 = arr[3]
	}
	if len(arr) > 4 {
		r.State2 = arr[4]
	}
	if r.State == "" {
		r.State = "ok"
	}
	return nil
}

type Chart struct {
	Label  string    `json:"label"`
	Points []float64 `json:"points"`
	Line   *float64  `json:"line,omitempty"`
}

type Bar struct {
	Label string  `json:"label"`
	Pct   float64 `json:"pct"`
}

type Action struct {
	ID      string   `json:"id"`
	Label   string   `json:"label"`
	Enabled bool     `json:"enabled"`
	Why     string   `json:"why,omitempty"`
	Confirm *Confirm `json:"confirm,omitempty"`
}

type Confirm struct {
	Title string `json:"title"`
	Body  string `json:"body"`
	Verb  string `json:"verb"`
}

type Camera struct {
	Recording bool   `json:"recording"`
	ElapsedS  int    `json:"elapsed_s"`
	MaxS      int    `json:"max_s"`
	SDFree    string `json:"sd_free"`
	HoursLeft int    `json:"hours_left"`
	Viewers   int    `json:"viewers"`
	LastClip  string `json:"last_clip"`
	ClipCount int    `json:"clip_count"`
	Note      string `json:"note"`
	Error     string `json:"error"`
	Phase     string `json:"phase"` // idle, starting, recording, stopping, saved, error
}
