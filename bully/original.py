from .node import Node
from .state import Status, TaskDefinition


class OriginalNode(Node):
    """The original Bully algorithm (Garcia-Molina 1982, Section III), see docs/bully-ref1.md.

    Node holds the state vector and the five message handlers. This class adds the four
    procedures a node starts itself, written from the paper's pseudocode:

        paper           method
        Election(i)     election()
        Recovery(i)     recovery()
        Check(i)        check()
        Timeout(i)      timeout()

    An election run by node i with every higher node down sends n - i AreYouThere, then
    i - 1 Halt, and one NewCoordinator and one Ready to each node that answered the Halt.
    """

    def recovery(self) -> None:
        with self._lock:
            self.state.h = None  # Nulstil hvem der sendte Halt
            self.storage.atomic_update(self.state)  # Gem tilstanden
        self.election()  # Start valgproceduren

    def election(self) -> None:
        # Låsen holdes kun om tilstanden, aldrig mens der ventes på svar fra en anden node
        with self._lock:
            halts = self._halts  # Et Halt modtaget herefter afbryder valget (STOP)

        while True:

            # Del 1 - undersøg om en node med højere id er til stede
            for node_id in range(self.id + 1, self.n + 1):
                if self._stopped(halts):
                    return
                if self.comm.probe(node_id):
                    return  # En højere node lever - opgiv valget

            # Ingen højere node svarede
            with self._lock:
                if self._halts != halts:  # Haltet af en anden node - opgiv valget
                    return
                self.stop_processing()  # Stop noders arbejde
                self.state.s = Status.ELECTION  # Status = ELECTION
                self.state.h = self.id  # Markér Node der starter valget
                self.state.up = set()  # Tom sæt - Nulstiller deltagere
                self.storage.atomic_update(self.state)  # Gem tilstanden

            # Del 2 - send HALT besked til nodes med lavere id
            for node_id in range(self.id - 1, 0, -1):  # Tæller ned med én(stop før nul)
                if self._stopped(halts):
                    return
                if self.comm.send_halt(node_id, self.id):  # Kommunikér halt (modtagers id, senders id)
                    with self._lock:
                        if self._halts != halts:
                            return
                        self.state.up.add(node_id)  # Tilføjer deltagere til sættet i state (modtagers id)
                        self.storage.atomic_update(self.state)  # Gem tilstanden

            # Alle lavere noder er kontaktet
            with self._lock:
                if self._halts != halts:
                    return
                self.state.c = self.id  # Sæt DENNE node som koordinator
                self.state.s = Status.REORGANIZATION  # Sæt status som reorganization
                self.storage.atomic_update(self.state)  # Gem tilstanden i lageret
                participants = sorted(self.state.up)

            restart = False  # Sæt restart variabel til false

            # Videregiv hvem Koordinator er
            for node_id in participants:
                if self._stopped(halts):
                    return
                if not self.comm.send_new_coordinator(node_id, self.id):  # Hvis true returneres udfør ikke blokken
                    restart = True
                    break

            if restart:  # Hvis restart er sandt spræng resten over og gå til starten af while løkken
                continue

            # Opret opgavebeskrivelse med deltager og koordinator
            task = TaskDefinition(
                participants=tuple(sorted(participants + [self.id])),
                application_algorithm="behandl opgaver",
            )

            with self._lock:
                if self._halts != halts:
                    return
                self.state.d = task  # Gem koordinators opgavebeskrivelse
                self.storage.atomic_update(self.state)

            # Send opgavebeskrivelse
            for node_id in participants:
                if self._stopped(halts):
                    return
                if not self.comm.send_ready(node_id, self.id, task):
                    restart = True
                    break

            if restart:
                continue

            # Alle deltagere har svaret
            with self._lock:
                if self._halts != halts:
                    return
                self.state.s = Status.NORMAL
                self.storage.atomic_update(self.state)
                self.processing = True
            return

    def check(self) -> None:
        # Kun én koordinator i normal
        with self._lock:
            if self.state.s != Status.NORMAL or self.state.c != self.id:
                return
        # Undersøg de andre noder
        for node_id in range(1, self.n + 1):
            if node_id == self.id:
                continue

            normal = self.comm.query_normal(node_id)

            # En levende node er ikke normal
            if normal is False:
                self.election()
                return

    def timeout(self) -> None:
        with self._lock:
            status = self.state.s
            coordinator_id = self.state.c

        if status in (Status.NORMAL, Status.REORGANIZATION):
            # Ingen koordinator - start valg
            if coordinator_id is None:
                self.election()
                return

            # Vi er selv koordinator
            if coordinator_id == self.id:
                return

            # Koordinatoren svarer ikke
            if not self.comm.probe(coordinator_id):
                self.election()

        else:
            self.election()
