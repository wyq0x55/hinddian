"""Keep existing SessionStart registrations quiet and validate configuration."""
from hook_runtime import quiet


@quiet
def main() -> None:
    from capture import settings

    settings()


if __name__ == "__main__":
    main()
