package main

import (
	"github.com/ScreenShare/server/cmd"
	pmode "github.com/ScreenShare/server/config/mode"
)

var (
	version    = "unknown"
	commitHash = "unknown"
	mode       = pmode.Dev
)

func main() {
	pmode.Set(mode)
	cmd.Run(version, commitHash)
}
