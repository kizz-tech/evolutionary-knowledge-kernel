import sys

if len(sys.argv) > 2 and sys.argv[1] == 'observe' and sys.argv[2] == '--event':
    # Host hook: runs on every prompt and turn end, so it skips the application imports.
    from .adapters.observe_hook import main as hook
    raise SystemExit(hook(sys.argv[2:]))

from .cli import main

raise SystemExit(main())
