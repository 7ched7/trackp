import argparse
import sys
from logger import logger
from constants import APP_NAME, RED, YELLOW, BOLD, RESET
from datetime import datetime, date
from client import Client
from server import Server
from daemonize import daemonize
from __version__ import __version__

class CliManager:
    class CustomArgumentParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            if "invalid choice" in message:
                start_index = message.find("choose from") + len("choose from")
                choices_part = message[start_index:].strip()
                choices = choices_part.strip("()").split(", ")
                available_commands = ", ".join(choices)
                print(f"{RED}invalid command{RESET}\n{BOLD}Choose from:{RESET} {YELLOW}{available_commands}{RESET}")
            else:
                logger.error(message)
            sys.exit(2) 
    
    def __init__(self):
        self.client = Client()
        self.server = Server()

    def _len_check(self, s: str) -> str:
        min_length = 1
        max_length = 24
        if len(s) >= min_length and len(s) <= max_length:
            return s
        raise argparse.ArgumentTypeError(f"id length must be between {min_length} and {max_length}")

    def create_parser(self) -> None:
        parser = self.CustomArgumentParser(
            prog=APP_NAME,
            description="Keep track of process runtime",
        )
        parser.add_argument("-v", "--version", action="version", version=f"v{__version__}")

        subparsers = parser.add_subparsers(dest="command")
        
        server_parser = subparsers.add_parser("server", help="manage server")
        server_subparser = server_parser.add_subparsers(dest="subcommand", required=True)
        
        server_subparser.add_parser("run", help=argparse.SUPPRESS) 
        server_start_parser = server_subparser.add_parser("start", help="start the server")
        server_status_parser = server_subparser.add_parser("status", help="show the status of the server")
        server_stop_parser = server_subparser.add_parser("stop", help="stop the server")
        
        ls_parser = subparsers.add_parser("ls", help="list all processes")

        add_parser = subparsers.add_parser("add", help="start tracking a process")
        add_parser.add_argument("process", help="process name or pid to track")
        add_parser.add_argument("-n", "--name", type=self._len_check, help="add custom tracking id")
        add_parser.add_argument("--fg", action="store_true", help="foreground mode")

        rm_parser = subparsers.add_parser("rm", help="stop tracking a process")
        rm_parser.add_argument("id", help="id of the tracked process to stop")
        rm_parser.add_argument("-v", "--verbose", action="store_true", help="show what is being done")

        ps_parser = subparsers.add_parser("ps", help="show the status of tracked processes")
        ps_parser.add_argument("-a", "--all", action="store_true", help="show both currently tracked and stopped processes")
        ps_parser.add_argument("-d", "--detailed", action="store_true", help="show detailed information about tracked processes")

        rename_parser = subparsers.add_parser("rename", help="rename tracking id of a process")
        rename_parser.add_argument("id", help="current tracking id")
        rename_parser.add_argument("new_id", type=self._len_check, help="new tracking id")
        rename_parser.add_argument("-v", "--verbose", action="store_true", help="show what is being done")

        report_parser = subparsers.add_parser("report", help="show report")
        report_parser.add_argument("-s", "--start", default=datetime.combine(date.today(), datetime.min.time()), help="start date (e.g., \"2 months ago\", \"1 week ago\", \"2025-06-12\")")
        report_parser.add_argument("-e", "--end", default=datetime.now(), help="end date (e.g., \"today\", \"yesterday\", \"2025-07-12\")")

        config_parser = subparsers.add_parser("config", help="manage configuration")
        config_subparsers = config_parser.add_subparsers(dest="subcommand", required=True)

        config_set_parser = config_subparsers.add_parser("set", help="set configuration")
        config_set_parser.add_argument("-i", "--ip", help="set the ip address")
        config_set_parser.add_argument("-p", "--port", type=int, help="set the port number")
        config_set_parser.add_argument("-l", "--limit", type=int, help="set the maximum number of concurrently tracked processes")
        config_set_parser.add_argument("-v", "--verbose", action="store_true", help="show what is being done")
        config_show_parser = config_subparsers.add_parser("show", help="show the current configuration")

        reset_parser = subparsers.add_parser("reset", help="reset program")
        reset_parser.add_argument("target", choices=["all", "config", "logs"], help="what to reset")
        reset_parser.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
        reset_parser.add_argument("-v", "--verbose", action="store_true", help="show what is being done")

        args = parser.parse_args()

        if args.command == None: parser.print_help()

        self._arg_controller(args)
    
    def _arg_controller(self, args: argparse.Namespace) -> None:
        command = args.command
        client = self.client 
        server = self.server
        
        if command == "server":
            subcommand = args.subcommand
            
            if subcommand == "run":
                server.run_server()
                return
            elif subcommand == "start":
                daemonize(server.run_server)()  
                return                     
            elif subcommand == "status":
                client.status_handler()
            elif subcommand == "stop":
                client.stop_handler()

            return

        command_handlers = {
            "ls": client.ls_handler,
            "add": lambda: daemonize(client.add_handler)(args),
            "rm": lambda: client.rm_handler(args),
            "ps": lambda: client.ps_handler(args),
            "rename": lambda: client.rename_handler(args),
            "report": lambda: client.report_handler(args),
            "config": lambda: client.config_handler(args),
            "reset": lambda: client.reset_handler(args)
        }

        if command in command_handlers:
            command_handlers[command]()