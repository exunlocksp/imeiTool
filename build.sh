#!/bin/bash
# Alias: clean + pyarmor + đóng gói (xem build_mac.sh)
exec "$(dirname "$0")/build_mac.sh" "$@"
