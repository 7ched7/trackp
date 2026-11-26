import socket
import sys
import json
from threading import Event
from logger import logger
from typing import Union, Optional

class ClientSocketManager:
    def __init__(self, ip: str, port: int, timeout: int = 5):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.client_socket: Optional[socket.socket] = None

    def create_connection(self, return_bool: bool=False) -> None:
        try:            
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(self.timeout)

            self.client_socket.connect((self.ip, self.port))
            if return_bool: return True
        except ConnectionRefusedError:
            if return_bool: return False
            logger.error("Server is down")
            sys.exit(1)
        except socket.gaierror:
            if return_bool: return False
            logger.error(f"Address-related error connecting to {self.ip}:{self.port}")
            sys.exit(1)
        except socket.error:
            if return_bool: return False
            logger.error(f"There may be a problem with the host ip address and port configuration")
            sys.exit(1)
        except Exception as e:
            if return_bool: return False
            logger.error(e)
            sys.exit(1)

    def is_socket_running(self, return_bool: bool=False) -> None:
        try:
            with socket.create_connection((self.ip, self.port), timeout=self.timeout):
                if return_bool: return True
                raise Exception("Cannot be performed while the server is running")
        except (socket.error, socket.timeout, OSError, socket.gaierror):
            if return_bool: return False
            pass
        except Exception as e:
            if return_bool: return False
            logger.error(e)
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(1)

    def is_ip_valid(self, ip: str, port: int) -> bool:
        sock = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.bind((ip, port))
            sock.listen(1)
            return True
        except PermissionError:
            logger.error(f"Permission denied on {ip}:{port}")
            sys.exit(1)
        except OSError as e:
            logger.error(f"Failed to bind {ip}:{port}: {str(e)}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"An error occurred when trying to connect to {ip}:{port}: {str(e)}")
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(1)
        finally:
            if sock: sock.close()

    def send_data(self, data: Union[str, dict], wait_for_response: bool=True, event: Event=None) -> Optional[str]:
        if isinstance(data, dict):
            data = json.dumps(data)

        try:
            if not self.client_socket:
                raise Exception("Socket not initialized, please create connection first")
            
            self.client_socket.sendall(data.encode("utf-8"))

            # optionally listen for the response from the server
            if wait_for_response:
                received_data = self.client_socket.recv(4096)
                return received_data.decode("utf-8")
        except (BrokenPipeError, ConnectionResetError, socket.error):
            if event: 
                event.set()
            self.client_socket.close()
            sys.exit(1)