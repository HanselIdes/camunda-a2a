"""Own a unique Compose project and reserve loopback ports before startup."""
import secrets
import socket
import subprocess
from pathlib import Path


def write_secret_store(private_root, values):
    root = Path(private_root)
    root.chmod(0o700)
    store = root / "store"
    store.mkdir(mode=0o755)
    store.chmod(0o755)
    for name, value in values.items():
        path = store / name
        path.write_text(value)
        path.chmod(0o444)
    return store


class IsolatedCompose:
    def __init__(self, compose, env):
        self.env = env
        self.project = "a2a-proof-" + secrets.token_hex(16)
        self.command = ["docker", "compose", "-p", self.project, "-f", str(compose)]
        self.started = False
        self.reservations = []
        try:
            for name in ("PROOF_ENGINE_PORT", "PROOF_CONNECTORS_PORT"):
                reservation = socket.socket()
                self.reservations.append(reservation)
                reservation.bind(("127.0.0.1", 0))
                env[name] = str(reservation.getsockname()[1])
        except Exception:
            self.close()
            raise

    def start(self):
        label = "label=com.docker.compose.project=" + self.project
        for resource, verb in (("container", "ls"), ("network", "ls"), ("volume", "ls")):
            found = subprocess.run(["docker", resource, verb, "-q", "--filter", label],
                                   check=True, capture_output=True, text=True)
            if found.stdout.strip():
                raise RuntimeError("Refusing to reuse a pre-existing Compose project")
        # Docker performs the final exclusive bind; a competing port claim fails startup,
        # never attaches to or tears down the competing service.
        self.release_ports()
        self.started = True
        subprocess.run(self.command + ["up", "-d", "--wait", "--wait-timeout", "300"],
                       env=self.env, check=True)

    def release_ports(self):
        for reservation in self.reservations:
            reservation.close()
        self.reservations.clear()

    def close(self):
        self.release_ports()
        if self.started:
            subprocess.run(self.command + ["down"], env=self.env, check=True)
            self.started = False
