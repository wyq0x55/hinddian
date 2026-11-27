"""Keep existing SessionStart registrations quiet and validate configuration."""
from hook_runtime import quiet, run_hook


@quiet
def main() -> None:
    from capture import settings

    settings()


if __name__ == "__main__":
    run_hook(main)
