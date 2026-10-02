"""One active application entry; historical runtimes are explicit replay artifacts."""
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] == ['observe', '--event'] or (len(argv) > 1 and argv[0] == 'observe' and argv[1] == '--event'):
        from .adapters.observe_hook import main as hook
        return hook(argv[1:])
    if argv and argv[0] == 'observe':
        from .adapters.observe_cli import main as observe_main
        return observe_main(argv[1:])
    if argv and argv[0] in {'work','queue','task','source','guide','improve'}:
        from .adapters.activity_cli import main as activity_main
        return activity_main(argv[0],argv[1:])
    if argv and argv[0] == 'method':
        from .adapters.method_cli import main as method_main
        return method_main(argv[1:])
    if argv and argv[0] == 'project':
        from .adapters.projection_cli import main as project_main
        return project_main(argv[1:])
    if argv == ['--version']:
        from . import __version__
        print(f'EKK {__version__} (record format 0.1)')
        return 0
    from .adapters.command_line import main as current_main
    return current_main(argv or ['--help'])
