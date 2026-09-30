# add-server-version-visibility

meridian version only prints a static, never-bumped package version with no git commit info; no MCP tool exposes what code a running server process actually has loaded, so an editable install that changed on disk after process start (git pull without restart) is invisible
