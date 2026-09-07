"""One active application entry; historical runtimes are explicit replay artifacts."""
import sys
from .adapters.command_line import main as current_main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'method':
        from .adapters.method_cli import main as method_main
        return method_main(argv[1:])
    if argv == ['--version']:
        from . import __version__
        print(f'EKK {__version__} (record format 0.1)')
        return 0
    return current_main(argv or ['--help'])
