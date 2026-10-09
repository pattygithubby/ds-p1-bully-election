from .original import OriginalNode
from .state import Status, TaskDefinition


class ImprovedNode(OriginalNode):
    """Bully with one message fewer per participant: NewCoordinator is merged into Ready.

    The original sends Halt, NewCoordinator and Ready to every lower node: 3(i - 1) messages
    for node i. The task definition is already known when the Halt round is over, so here
    Ready also announces the coordinator: 2(i - 1) messages.

        original    Halt -> NewCoordinator -> Ready      Election -> Reorganization -> Normal
        improved    Halt -> Ready                        Election -> Normal

    Halt stays a separate step. The guard that protects NewCoordinator in the original
    (s = Election and h = sender) moves to Ready, so a message from a superseded election
    is still rejected.
    """

    def ready(self, sender_id: int, task: TaskDefinition) -> None:
        with self._lock:
            # Noden skal være i Election og afsender skal matche seneste Halt
            # (betingelsen fra NewCoordinator i den originale algoritme)
            if self.state.s == Status.ELECTION and self.state.h == sender_id:
                self.state.c = sender_id  # Sæt koordinator til sender_id
                self.state.d = task  # Gem opgavebeskrivelsen
                self.state.s = Status.NORMAL  # Status - Normal
                self.storage.atomic_update(self.state)  # Gem før arbejdet tillades
                self.processing = True  # Markér at noden må udføre arbejde

    def election(self) -> None:
        # Som OriginalNode.election, men uden runden med NewCoordinator
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

            # Alle lavere noder er kontaktet - opgavebeskrivelsen kan oprettes med det samme
            with self._lock:
                if self._halts != halts:
                    return
                participants = sorted(self.state.up)
                task = TaskDefinition(
                    participants=tuple(sorted(participants + [self.id])),
                    application_algorithm="behandl opgaver",
                )
                self.state.c = self.id  # Sæt DENNE node som koordinator
                self.state.s = Status.REORGANIZATION  # Sæt status som reorganization
                self.state.d = task  # Gem koordinators opgavebeskrivelse
                self.storage.atomic_update(self.state)  # Gem tilstanden i lageret

            restart = False  # Sæt restart variabel til false

            # Ready fortæller både hvem koordinator er og hvad opgaven er
            for node_id in participants:
                if self._stopped(halts):
                    return
                if not self.comm.send_ready(node_id, self.id, task):
                    restart = True
                    break

            if restart:  # En deltager svarede ikke - start valget forfra
                continue

            # Alle deltagere har svaret
            with self._lock:
                if self._halts != halts:
                    return
                self.state.s = Status.NORMAL
                self.storage.atomic_update(self.state)
                self.processing = True
            return
