from manager.cli import CliManager

def main() -> None:
    cli_manager = CliManager()
    cli_manager.create_parser() 

if __name__ == "__main__":
    main()