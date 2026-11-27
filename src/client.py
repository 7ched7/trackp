import threading
import psutil
import time
import sys
import os
import ipaddress
import signal
import secrets
import select
import json
import dateparser
from threading import Event
from queue import Queue, Empty
from pathlib import Path
from typing import Any, Dict, Optional, Union
from manager import (
    ConfigManager,
    LogManager,
    ClientSocketManager
)
from logger import logger
from constants import MAX_PROCESS_LIMIT, is_windows, APP_NAME, GREEN, GREY, YELLOW, BOLD, RESET  
from datetime import datetime, timedelta
from argparse import Namespace 
from tabulate import tabulate

class Client:
    def __init__(self):
        self.config_manager = ConfigManager()
        ip, port, _ = self.config_manager.get_config()

        self.log_manager = LogManager() 
        self.client_socket_manager = ClientSocketManager(ip, port)

        self.event: Event = Event()
        self.queue = Queue()
        self.process_name: None | str = None
        self.id: None | str = None
        self.process_pid: None | int = None
        self.start_time: None | datetime = None
    
    def _connection_handler(self) -> None:     
        last_ping_time = time.time()
        PING_INTERVAL = 10.0

        try:
            logger.info("Connection handler started")

            while not self.event.is_set():
                now = time.time()
                ready_to_read, _, _ = select.select([self.client_socket_manager.client_socket], [], [], 1)

                if ready_to_read:
                    try:
                        data = self.client_socket_manager.client_socket.recv(4096)

                        if data.decode("utf-8").strip() == "stop":
                            logger.info("Received stop signal, stopping connection handler")
                            self.event.set()
                            break

                        if not data:
                            logger.info("Connection closed by remote")
                            self.event.set()
                            break
                    except (ConnectionResetError, OSError):
                        logger.warning("Connection lost")
                        self.event.set()
                        break
                
                # get the message from the thread tracking the process
                while not self.queue.empty():
                    try:
                        json_data = self.queue.get_nowait()
                        self.client_socket_manager.send_data(json_data, wait_for_response=False)
                    except Empty:
                        break
                
                if now - last_ping_time >= PING_INTERVAL:
                    self.client_socket_manager.send_data("ping", wait_for_response=False, event=self.event)
                    last_ping_time = now                
        except Exception as e:
            logger.error(f"Error during connection control: {e}")
            sys.exit(1)
        finally:
            self.event.set()
            logger.info("Closing client socket")
            self.client_socket_manager.client_socket.close()

    def _notify_socket(self) -> None:
        _, _, limit = self.config_manager.get_config()

        json_data = {
            "command": "add",
            self.id: {
                "process_name": self.process_name,
                "pid": self.process_pid,
                "track_pid": os.getpid(),
                "start_time": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                "session_time": time.time() if self.process_pid else None,
                "runtime": 0.0,
                "status": "running" if self.process_pid else "stopped",
                "conn": None
            }
        }

        try:
            logger.info("Sending data to server for tracking...")
            received_data = self.client_socket_manager.send_data(json_data).lower()

            if received_data == "duplicate id":
                raise Exception(f"ID \"{self.id}\" is already in use")
            elif received_data == "duplicate process":
                raise Exception(f"Already tracking \"{self.process_name}\"")
            elif received_data == "limit":
                process_word = "process" if limit == 1 else "processes"
                raise Exception(f"Maximum process tracking limit exceeded. You can only run up to {limit} {process_word} simultaneously")
        except Exception as e:
            logger.error(e)
            self.client_socket_manager.client_socket.close()
            sys.exit(1)

    def _get_process(self, process: str) -> Optional[Dict[str, Any]]:
        target: Union[str, int] = int(process) if process.isdigit() else process

        for proc in psutil.process_iter(["name", "pid"]):
            if self._is_self_tracking_process(proc):
                continue

            name = proc.info.get("name")
            pid = proc.info.get("pid")

            if isinstance(target, int) and target == pid:
                return proc.info
            elif isinstance(target, str) and name and target.lower() == name.lower():
                return proc.info
            
        return None
    
    def _is_self_tracking_process(self, proc: psutil.Process) -> bool:
        if proc.pid == os.getpid():
            return True
        
        name = f"{APP_NAME}.exe" if is_windows else APP_NAME
        if proc.info["name"].lower() == name:
            return True

        try:
            exe_path = Path(proc.exe()).resolve()
            app_path = Path(f"/usr/local/bin/{APP_NAME}").resolve()
            if exe_path == app_path:
                return True
        except:
            pass

        try:
            if proc.cmdline() and APP_NAME in proc.cmdline([0]):
                return True
        except:
            pass

        return False

    def _track_process(self) -> None:
        logger.info(f"Tracking started: {self.process_name}")
        
        if self.process_pid:
            self.log_manager.save_start_time(self.process_name, self.start_time)
        
        save_interval = timedelta(minutes=5)
        next_save = datetime.now() + save_interval

        while True:
            process_info = self._get_process(self.process_name)
            now = datetime.now()

            if process_info:
                if (self.process_pid is None or 
                    (self.process_pid is not None and self.process_pid != process_info["pid"])):
                    
                    logger.info(f"Process {self.process_name} started")

                    json_data = {
                        "command": "update", 
                        "status": "running", 
                        process_info["name"]: process_info["pid"],
                        "session_time": time.time()
                    }
                    self.queue.put(json_data)

                self.process_name = process_info["name"]
                self.process_pid = process_info["pid"]

                if not self.start_time:
                    self.start_time = now
                    self.log_manager.save_start_time(self.process_name, self.start_time)
                    next_save = self.start_time + save_interval
            elif not process_info and self.process_pid and self.start_time:
                logger.info(f"Process {self.process_name} stopped")

                json_data = {
                    "command": "update", 
                    "status": "stopped", 
                    self.process_name: None,
                    "session_time": None
                }
                self.queue.put(json_data)
                self.log_manager.save_end_time(self.process_name, self.start_time)
                self.process_pid = None
                self.start_time = None

            if now >= next_save and self.start_time:
                self.log_manager.save_end_time(self.process_name, self.start_time)
                next_save = now + save_interval
            
            # stop signal
            if self.event.is_set():
                logger.info(f"Stopping tracking of {self.process_name}")
                if self.start_time:
                    self.log_manager.save_end_time(self.process_name, self.start_time)
                break
                    
            time.sleep(1)

    def _signal_handler(self) -> None:
        signal.signal(signal.SIGTERM, self._save_and_exit)
        signal.signal(signal.SIGINT, self._save_and_exit)

    def _wait_for_interrupt(self) -> None:
        try:
            while not self.event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self._save_and_exit(None, None)
           
    def _save_and_exit(self, s, f) -> None:
        start_time = self.start_time
        process_name = self.process_name

        if start_time:
            self.log_manager.save_end_time(process_name, start_time)
            
        self.event.set()

    def add_handler(self, args: Namespace) -> None:
        self.client_socket_manager.create_connection()
        logger.info("Connection established to the server")

        logger.info(f"Getting process information for {args.process}")
        process_info = self._get_process(args.process)

        if not process_info:
            logger.info(f"Process information could not be received, waiting for {args.process} to start")
            self.process_name = args.process
            self.process_pid = None
            self.start_time = None
        else:
            self.process_name = process_info["name"]
            self.process_pid = process_info["pid"]
            self.start_time = datetime.now()
            
        self.id = args.name or secrets.token_hex(6)
        logger.info(f"Generated/Provided ID: {self.id}")

        self._notify_socket()
        if not is_windows:
            self._signal_handler()
        
        t1 = threading.Thread(target=self._connection_handler)
        t2 = threading.Thread(target=self._track_process)
        t1.start()  
        t2.start()

        if is_windows: 
            self._wait_for_interrupt()

        t1.join()
        t2.join()

    def stop_handler(self) -> None:
        self.client_socket_manager.create_connection()

        try:   
            self.client_socket_manager.send_data({"command": "stop"}, wait_for_response=False)
            logger.info("Stopping the server")

        except Exception as e:
            logger.error(e)
            sys.exit(1)
        finally:
            self.client_socket_manager.client_socket.close()

    def ls_handler(self) -> None:
        headers = [f"{YELLOW}USER{RESET}", f"{YELLOW}PID{RESET}", f"{YELLOW}PROCESS{RESET}"]
        rows = []

        for proc in psutil.process_iter(["username", "pid", "name"]):
            try:
                info = proc.info
                row = [info["username"], info["pid"], info["name"]]
                rows.append(row)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        print(tabulate(rows, headers, tablefmt="plain", numalign="left"))

    def status_handler(self) -> None:
        self.client_socket_manager.create_connection()
        data = self.client_socket_manager.send_data({ "command": "status" })

        try: 
            data = json.loads(data)

            ip = data.get("ip")
            port = data.get("port")
            tracked_processes = data.get("tracked_processes")
            running = data.get("running")
            stopped = data.get("stopped")

            print(f"{BOLD}SERVER:{RESET} running")
            print(f"{BOLD}HOST:{RESET} {ip}:{port}")
            print(f"{BOLD}TRACKED PROCESSES:{RESET} {tracked_processes} { f"{GREY}({running} running, {stopped} stopped){RESET}" if tracked_processes != 0 else "" } ")

        except json.decoder.JSONDecodeError:
            logger.error(f"There was a problem retrieving the status data, please try again")
            sys.exit(1)
        finally:
            self.client_socket_manager.client_socket.close()

    def rm_handler(self, args: Namespace) -> None:
        self.client_socket_manager.create_connection()

        try:   
            data = self.client_socket_manager.send_data({ "command": "rm", "process": args.id }).lower()

            if data == "ok" and args.verbose:
                logger.info(f"Tracking stopped: {args.id}")

            if data == "error":
                raise Exception(f"{args.id} is not being tracked")
        
        except Exception as e:
            logger.error(e)
            sys.exit(1)
        finally:
            self.client_socket_manager.client_socket.close()

    def ps_handler(self, args: Namespace) -> None:
        self.client_socket_manager.create_connection()
        data = self.client_socket_manager.send_data({ "command": args.command, "all": args.all, "detailed": args.detailed })

        try:
            data = json.loads(data)

            headers = [f"{YELLOW}TRACK ID{RESET}", f"{YELLOW}PROCESS{RESET}", f"{YELLOW}STARTED{RESET}", f"{YELLOW}RUNTIME{RESET}", f"{YELLOW}STATUS{RESET}"]
            if args.detailed:
                headers.insert(2, f"{YELLOW}PID{RESET}")
                headers.append(f"{YELLOW}CONNECTION{RESET}")
            rows = []

            for track_id, process_info in data.items():
                pl = []
                pl.append(track_id)

                runtime = process_info["runtime"]
                if isinstance(runtime, float):
                    runtime_td = timedelta(seconds=runtime)
                    process_info["runtime"] = self.timedelta_to_str(runtime_td)

                pl.extend([ "--" if info == None else info for info in process_info.values() ])
                rows.append(pl)

            print(tabulate(rows, headers, tablefmt="plain", numalign="left"), end="\n\n")
        except json.decoder.JSONDecodeError:
            logger.error(f"There was a problem retrieving the tracked programs data, please try again")
            sys.exit(1)
        finally:
            self.client_socket_manager.client_socket.close()

    def rename_handler(self, args: Namespace) -> None:
        self.client_socket_manager.create_connection()

        id = args.id
        new_id = args.new_id

        try:   
            data = self.client_socket_manager.send_data({ "command": "rename", "process": id, "new_id": new_id }).lower()

            if data == "ok" and args.verbose:
                logger.info(f"ID \"{id}\" successfully renamed to \"{new_id}\"")
            elif data == "error":
                raise Exception(f"{id} is not being tracked")
            elif data == "duplicate":
                raise Exception(f"ID \"{new_id}\" is already in use")
        except Exception as e:
            logger.error(e)
            sys.exit(1)
        finally:
            self.client_socket_manager.client_socket.close()

    def report_handler(self, args: Namespace) -> None:
        try:
            start_flag = dateparser.parse(str(args.start))
            end_flag = dateparser.parse(str(args.end))

            if start_flag is None or end_flag is None:
                raise AttributeError

            if start_flag >= end_flag:
                raise Exception("The start date cannot be greater than or the same as the end date")
        except AttributeError:
            logger.error("Invalid date. Expected format: natural language or ISO date")     
            sys.exit(1)
        except Exception as e:
            logger.error(e)     
            sys.exit(1)
        
        logs_dir = self.log_manager.logs_dir
        headers = [f"{YELLOW}PROCESS{RESET}", f"{YELLOW}TOTAL RUN TIME{RESET}", f"{YELLOW}ACTIVE DAYS{RESET}"]
        rows = []
        process_stats = {}

        dates_list = []
        curr_date = start_flag.date()

        while curr_date <= end_flag.date():
            dates_list.append(curr_date.strftime("%Y%m%d"))
            curr_date += timedelta(days=1)

        for date in dates_list:
            log_file = os.path.join(logs_dir, date)
            data = self.log_manager.get_logs(log_file)
            
            for process, time_info in data.items():
                for info in time_info:
                    start = max(datetime.fromisoformat(info["start_time"]), start_flag)
                    end = min(datetime.fromisoformat(info["end_time"]), end_flag)

                    elapsed_time = end - start

                    if elapsed_time.total_seconds() < 0:
                        continue

                    if process not in process_stats:
                        process_stats[process] = {
                            "total_time": timedelta(), 
                            "active_days": set(), 
                            "status": ""
                        }

                    process_stats[process]["total_time"] += elapsed_time
                    process_stats[process]["active_days"].add(start.date())

        connection = self.client_socket_manager.create_connection(return_bool=True)
        has_active = False
        
        # show asterisk (*) for active tracked processes
        if connection:
            data = self.client_socket_manager.send_data({"command": "report"})
            
            try:
                data = json.loads(data)
            except json.decoder.JSONDecodeError:
                logger.error(f"There was a problem retrieving the active processes data, please try again")
                sys.exit(1)

            for active_process in data["active_processes"]:
                if active_process in process_stats.keys():
                    process_stats[active_process]["status"] = "*"
                    has_active = True
        
        for process, info in process_stats.items():
            prefix = f"{GREEN}{info["status"]}{RESET}"
            rows.append([
                prefix + process, 
                self.timedelta_to_str(info["total_time"]), 
                len(info["active_days"])
            ])

        date_str = f"{start_flag.strftime("%Y/%m/%d %H:%M:%S")} - {end_flag.strftime("%Y/%m/%d %H:%M:%S")}"
        print(f"{BOLD}REPORT{RESET} | {date_str}", end="\n\n")
        print(tabulate(rows, headers, tablefmt="plain", numalign="left"), end="\n\n")

        if connection and has_active:
            print(f"{GREY}Note: Durations are updated every 5 minutes.{RESET}")
            print(f"{GREY}Active programs (*) are still running — the last ~5 minutes of usage may not be reflected yet.{RESET}")
            print(f"{GREY}Use \"ps\" to see real-time session durations.{RESET}", end="\n\n")

    def timedelta_to_str(self, td: timedelta) -> str:        
        total_seconds = int(td.total_seconds())
        
        hours = (total_seconds) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        return f"{hours}h {minutes}m {seconds}s"

    def reset_handler(self, args: Namespace) -> None:
        # check if server is running otherwise it will throw an error
        self.client_socket_manager.is_socket_running()

        target = args.target
        verbose = args.verbose
        yes = args.yes

        if not yes:
            try:
                confirm = input(f"This will reset {target.upper()} data. Are you sure? [y/N]: ").strip().lower()
                if confirm != "y":
                    logger.info("Reset cancelled")
                    return
            except (KeyboardInterrupt, EOFError):
                logger.info("Reset cancelled")
                return

        if target == "all":
            self._reset_config(verbose)
            self._reset_logs()
        elif target == "config":
            self._reset_config(verbose)
        elif target == "logs":
            self._reset_logs()

    def _reset_config(self, verbose: bool) -> None:
        self.config_manager.create_config()
        
        if verbose:
            logger.info("Configuration has been successfully reset to default values")

    def _reset_logs(self) -> None:
        logs_dir = self.log_manager.logs_dir

        for filename in os.listdir(logs_dir):
            file_path = os.path.join(logs_dir, filename)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    logger.error(f"Could not delete {filename}")

    def config_handler(self, args: Namespace) -> None:
        subcommand = args.subcommand

        if subcommand == "set":
            self._config_set_handler(args)
        elif subcommand == "show":
            self._config_show_handler()

    def _validate_args(self, args: Namespace) -> None:
        if not any([args.ip, args.port is not None, args.limit is not None]):
            raise ValueError("You must provide at least one of the following arguments: -i, -p, or -l")
        
        if args.ip:
            ipaddress.ip_address(args.ip)

        if args.port is not None and not (1 <= args.port <= 65535):
            raise ValueError("Invalid port number, port must be between 1 and 65535")

        if args.limit is not None:
            if args.limit > MAX_PROCESS_LIMIT:
                args.limit = MAX_PROCESS_LIMIT

                if args.verbose:
                    logger.warning(f"The specified limit is too high, it has been automatically set to the maximum limit of {MAX_PROCESS_LIMIT}")
                    
            elif args.limit < 1:
                args.limit = 1

                if args.verbose:
                    logger.warning("The specified limit cannot be 0 or a negative value, it has been automatically set to the minimum valid limit of 1")

    def _config_set_handler(self, args: Namespace) -> None:
        try:
            self._validate_args(args)
        except ValueError as e:
            logger.error(e)
            sys.exit(1)    

        ip, port, limit = self.config_manager.get_config()
        self.client_socket_manager.is_socket_running()

        i = args.ip or ip
        p = args.port or port
        l = args.limit or limit

        if args.ip or args.port:
            self.client_socket_manager.is_ip_valid(i, p)

        self.config_manager.create_config(i, p, l)

        if args.verbose:
            logger.info("Configuration has been saved successfully")

    def _config_show_handler(self) -> None:
        ip, port, limit = self.config_manager.get_config()
        print(f"{BOLD}HOST IP ADDRESS:{RESET}", ip)
        print(f"{BOLD}PORT:{RESET}", port)
        print(f"{BOLD}MAXIMUM PROCESS LIMIT:{RESET}", limit)