import threading

from .communication import Communication
from .state import Status, TaskDefinition
from .storage import SafeStorage


class Node:
    """Fælles grundlag for begge varianter af Bully-algoritmen, se docs/bully-ref1.md.

    Indeholder tilstandsvektoren S(i) i sikkert lager (antagelse 4) og de fem
    immediate procedures, som kaldes når en besked modtages:
        are_you_there, are_you_normal, halt, new_coordinator, ready
    Procedurerne som noden selv starter - election, recovery, check og timeout -
    implementeres af underklasserne (OriginalNode, ImprovedNode).
    """

    def __init__(
        self,
        node_id: int,
        n: int,
        comm: Communication,
        storage: SafeStorage,
    ):
        self.id = node_id  # Nodens id
        self.n = n  # Antal noder - id fra 1 til n
        self.comm = comm  # Kommunikation med de andre noder
        self.storage = storage  # Lager til nodens tilstand

        self.state = self.storage.load()  # Hent gemt tilstand eller ny starttilstand
        self.state.s = Status.DOWN  # Initialiser status - Down
        self.state.h = None  # Nulstil seneste node der sendte Halt
        self.storage.atomic_update(self.state)  # Gem tilstanden

        self.processing = False  # Noden udfører ikke arbejde endnu

        # Kritisk sektion om tilstanden - handlers og procedurer kan køre i hver sin tråd
        self._lock = threading.RLock()
        self._halts = 0  # Antal modtagne Halt - bruges til at afbryde et igangværende valg

    def are_you_there(self) -> bool:
        # Et svar viser at noden er til stede
        # Kommunikationslaget skal håndtere at en crashet node ikke svarer
        return True

    def are_you_normal(self) -> bool:
        # Undersøg om nodens status er Normal
        with self._lock:
            return self.state.s == Status.NORMAL

    def stop_processing(self) -> None:
        # Markér at noden ikke udfører arbejde
        # Et igangværende valg afbrydes af halt() via self._halts
        self.processing = False

    def _stopped(self, halts: int) -> bool:
        # STOP - er der modtaget et Halt siden valget startede?
        with self._lock:
            return self._halts != halts

    def halt(self, sender_id: int) -> None:
        with self._lock:
            self._halts += 1  # STOP - et igangværende valg på denne node opgives
            self.state.s = Status.ELECTION  # Status - Election
            self.state.h = sender_id  # Gem id på noden der sendte Halt
            self.stop_processing()  # Stop nodens arbejde
            self.storage.atomic_update(self.state)  # Gem tilstanden

    def new_coordinator(self, sender_id: int) -> None:
        with self._lock:
            # Noden skal være i Election og afsender skal matche seneste Halt
            if self.state.s == Status.ELECTION and self.state.h == sender_id:
                self.state.c = sender_id  # Sæt koordinator til sender_id
                self.state.s = Status.REORGANIZATION  # Status - Reorganization
                self.storage.atomic_update(self.state)  # Gem tilstanden

    def ready(self, sender_id: int, task: TaskDefinition) -> None:
        with self._lock:
            # Noden skal være i Reorganization og afsender skal være koordinator
            if self.state.s == Status.REORGANIZATION and self.state.c == sender_id:
                self.state.d = task  # Gem opgavebeskrivelsen
                self.state.s = Status.NORMAL  # Status - Normal
                self.storage.atomic_update(self.state)  # Gem før arbejdet tillades
                self.processing = True  # Markér at noden må udføre arbejde

    def recovery(self) -> None:
        raise NotImplementedError

    def election(self) -> None:
        raise NotImplementedError

    def check(self) -> None:
        raise NotImplementedError

    def timeout(self) -> None:
        raise NotImplementedError
