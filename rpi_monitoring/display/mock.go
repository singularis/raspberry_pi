package main

func tile(id, label, state, big, cap, l2, l3 string, spark []float64) Tile {
	return Tile{ID: id, Label: label, State: state, Big: big, Cap: cap, L2: l2, L3: l3, Spark: spark, AgeS: 4,
		Pages: []Page{{Rows: []Row{{Label: "state", Value: state}, {Label: "value", Value: big}}}}}
}

func baseSnap() *Snapshot {
	s := &Snapshot{Schema: 1, TS: "2026-09-26T15:43:00+01:00", NextInS: 58, TempOut: "16\u00b0C", Humidity: "80%", Pressure: "1016"}
	s.Tiles = []Tile{
		tile("racoon", "RACOON", "ok", "37%", "cpu", "ram 41%", "56C 35W", []float64{30, 33, 37, 36, 37}),
		tile("worker", "WORKER", "ok", "1.8G", "ram free", "cpu 23%", "52C 9W", []float64{2.0, 1.9, 1.8, 1.8}),
		tile("gpu", "GPU", "off", "OFF", "since 23:00", "on 08:00", "", nil),
		tile("pi", "PI", "ok", "48C", "cpu temp", "ram 174M", "power ok", []float64{160, 170, 174}),
		tile("eateria", "EATERIA", "ok", "+23", "dishes today", "7d users 57", "prod+dev ok", []float64{200, 300, 420}),
		tile("backup", "BACKUP", "ok", "4d", "last ok", "next in 3d", "archive 61%", nil),
		tile("network", "NETWORK", "ok", "12ms", "wan", "dns 8ms", "wifi -58dBm", []float64{11, 12, 14, 12}),
		{ID: "camera", Label: "CAMERA", State: "idle", Big: "REC", Cap: "ready", L2: "SD 8.0G", L3: "~5h left", Screen: "camera",
			Camera: &Camera{Phase: "idle", MaxS: 1800, SDFree: "8.0G", HoursLeft: 5, Note: "live view pauses while recording"}},
	}
	s.Tiles[2].Pages = []Page{{Rows: []Row{
		{Label: "cpu", Value: "off", State: "off"},
		{Label: "ram free", Value: "off", State: "off"},
		{Label: "gpu", Value: "off", State: "off"},
		{Label: "gpu ram", Value: "off", State: "off"},
		{Label: "staging free", Value: "off", State: "off"},
		{Label: "/ free", Value: "off", State: "off"},
		{Label: "temp", Value: "off", State: "off"},
		{Label: "gpu temp", Value: "off", State: "off"},
		{Label: "k8s", Value: "off", State: "off"},
	}}}
	s.Tiles[5].Pages = []Page{{
		Rows: []Row{
			{Label: "staging free", Value: "off", State: "off"},
			{Label: "archive", Value: "off", State: "off"},
			{Label: "last", Value: "4d", State: "ok"},
		},
		Actions: []Action{
			{ID: "wake", Label: "Wake GPU", Enabled: true, Confirm: &Confirm{Title: "Wake GPU host?", Body: "Boots Proxmox and racoon-gpu", Verb: "Wake"}},
			{ID: "backup", Label: "Run backup", Enabled: true, Confirm: &Confirm{Title: "Run backup now?", Body: "Starts the staging sync", Verb: "Run"}},
		},
	}}
	s.Tiles[0].Pages = []Page{
		{Rows: []Row{
			{Label: "cpu", Value: "37%", State: "ok"},
			{Label: "ram free", Value: "63% 40G", State: "ok"},
			{Label: "/ free", Value: "34% 117G", State: "ok"},
			{Label: "ssd free", Value: "48% 461G", State: "ok"},
			{Label: "hdd free", Value: "26% 480G", State: "ok"},
			{Label: "temp", Value: "56C", State: "ok"},
			{Label: "k8s", Value: "up", State: "ok"},
		}},
		{Rows: []Row{{Label: "nodes", Value: "2/3"}, {Label: "pods", Value: "ok"}}},
	}
	s.Tiles[1].Pages = []Page{{Rows: []Row{
		{Label: "cpu", Value: "23%", State: "ok"},
		{Label: "ram free", Value: "27% 1.9G", State: "ok"},
		{Label: "/ free", Value: "41% 49G", State: "ok"},
		{Label: "temp", Value: "52C", State: "ok"},
		{Label: "k8s", Value: "up", State: "ok"},
	}}}
	s.Tiles[3].Pages = []Page{{Rows: []Row{
		{Label: "cpu", Value: "10%", State: "ok"},
		{Label: "ram free", Value: "60% 219M", State: "ok"},
		{Label: "sd free", Value: "57% 8.0G", State: "ok"},
		{Label: "temp", Value: "48C", State: "ok"},
		{Label: "power", Value: "ok", State: "ok"},
	}}}
	s.Tiles[4].Pages = []Page{{Rows: []Row{
		{Label: "scans", Value: "8", State: "ok", Value2: "5", State2: "ok"},
		{Label: "users", Value: "1", State: "ok", Value2: "0", State2: "stale"},
		{Label: "anon", Value: "3", State: "ok", Value2: "2", State2: "ok"},
		{Label: "ascans", Value: "4", State: "ok", Value2: "1", State2: "ok"},
		{Label: "7d scans", Value: "40", State: "ok", Value2: "30", State2: "ok"},
		{Label: "7d users", Value: "9", State: "ok", Value2: "7", State2: "ok"},
		{Label: "dev", Value: "up", State: "ok"},
	}}}
	return s
}

func mockSet() map[string]*Snapshot {
	ok := baseSnap()
	mixed := baseSnap()
	mixed.Summary.Warn = 1
	mixed.Summary.Worst = "worker"
	mixed.Tiles[1].State = "warn"
	mixed.Tiles[1].Big = "0.9G"
	mixed.Tiles[2].State = "off"
	rec := baseSnap()
	rec.Tiles[7].State = "crit"
	rec.Tiles[7].Big = "12m"
	rec.Tiles[7].Camera.Recording = true
	rec.Tiles[7].Camera.Phase = "recording"
	rec.Tiles[7].Camera.ElapsedS = 12 * 60
	eater := baseSnap()
	eater.Summary.Crit = 1
	eater.Summary.Worst = "eateria"
	eater.Tiles[4].State = "crit"
	eater.Tiles[4].L3 = "prod fail"
	claw := baseSnap()
	claw.Summary.Warn = 1
	claw.Summary.Worst = "gpu"
	claw.Tiles[2].State = "warn"
	claw.Tiles[2].Big = "41%"
	claw.Tiles[2].Cap = "gpu"
	claw.Tiles[2].L2 = "claw: channel"
	return map[string]*Snapshot{"home_ok": ok, "home_mixed": mixed, "recording": rec, "eateria_crit": eater, "gpu_claw": claw}
}
