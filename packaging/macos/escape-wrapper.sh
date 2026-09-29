#!/bin/bash
# Installed as /usr/local/bin/escape: runs the build that matches this Mac's CPU.
exec "/usr/local/lib/escape-engine/$(uname -m)/escape/escape" "$@"
