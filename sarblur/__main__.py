import sys


def entry() -> int:
    if "--self-test" in sys.argv:
        from sarblur.selftest import run
        i = sys.argv.index("--self-test")
        return run(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    from sarblur.ui import main
    return main()


if __name__ == "__main__":
    sys.exit(entry())
