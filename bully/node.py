from .communication import Communication
from .state import Status, TaskDefinition
from .storage import SafeStorage


class Node:
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

    def are_you_there(self) -> bool:
        # Et svar viser at noden er til stede
        # Kommunikationslaget skal håndtere at en crashet node ikke svarer
        return True

    def are_you_normal(self) -> bool:
        # Undersøg om nodens status er Normal
        return self.state.s == Status.NORMAL

    def stop_processing(self) -> None:
        # Markér at noden ikke udfører arbejde
        # Stopper endnu ikke faktisk kørende arbejde eller valg
        self.processing = False

    def halt(self, sender_id: int) -> None:
        self.state.s = Status.ELECTION  # Status - Election
        self.state.h = sender_id  # Gem id på noden der sendte Halt
        self.stop_processing()  # Stop nodens arbejde
        self.storage.atomic_update(self.state)  # Gem tilstanden

    def new_coordinator(self, sender_id: int) -> None:
        # Noden skal være i Election og afsender skal matche seneste Halt
        if self.state.s == Status.ELECTION and self.state.h == sender_id:
            self.state.c = sender_id  # Sæt koordinator til sender_id
            self.state.s = Status.REORGANIZATION  # Status - Reorganization
            self.storage.atomic_update(self.state)  # Gem tilstanden

    def ready(self, sender_id: int, task: TaskDefinition) -> None:
        # Noden skal være i Reorganization og afsender skal være koordinator
        if self.state.s == Status.REORGANIZATION and self.state.c == sender_id:
            self.state.d = task  # Gem opgavebeskrivelsen
            self.state.s = Status.NORMAL  # Status - Normal
            self.storage.atomic_update(self.state)  # Gem før arbejdet tillades
            self.processing = True  # Markér at noden må udføre arbejde

    def recovery(self) -> None:
        self.state.h = None  # Nulstil hvem der sendte Halt
        self.storage.atomic_update(self.state)  # Gem tilstanden
        self.election()  # Start valgproceduren

    def election(self) -> None:
        while True:

            for node_id in range (self.id +1, self.n+1) : 
                if self.comm.probe(node_id):
                    return

            # Ingen højere node svarede
            self.stop_processing() # Stop noders arbejde
            self.state.s = Status.ELECTION # Status = ELECTION
            self.state.h = self.id # Markér Node der starter valget
            self.state.up = set() # Tom sæt - Nulstiller deltagere
            self.storage.atomic_update(self.state) # Gem tilstanden 

            #Send HALT besked til nodes med lavere id
            for node_id in range(node_id -1, 0, -1): # Tæller ned med én(stop før nul)
                if self.comm.send_halt(node_id, self.id): # Kommunikér halt (modtagers id, senders id)
                    self.state.up.add(node_id) # Tilføjer deltagere til sættet i state (modtagers id)
                    self.storage.atomic_update(self.state) # Gem tilstanden 

            # Alle lavere noder er kontaktet
            self.state.c = self.id # Sæt DENNE node som koordinator
            self.state.s = Status.REORGANIZATION # Sæt status som reorganization 
            self.storage.atomic_update(self.state) # Gem tilstanden i lageret 

            restart = False # Sæt restart variabel til false

            # Videregiv hvem Koordinator er 
            for i in sorted(self.state.up):
                if not self.comm.send_new_coordinator(node_id, self.id): # Hvis true returneres udfør ikke blokken
                    restart = True 
                    break 

            if restart: # Hvis restart er sandt spræng resten over og gå til starten af while løkken 
                continue


            # Opret opgavebeskrivelse med deltager og koordinator

            task = TaskDefinition(
                participants=tuple(sorted(self.state.up | {self.id})),
                application_algorithm = "behandl opgaver"
            )

            self.state.d = task # Gem koordinators opgavebeskrivelse
            self.storage.atomic_update(self.state)

            # Send opgavebeskrivelse
            for node_id in sorted(self.state.up):
                if not self.comm.send_ready(node_id, self.id, task):
                    restart = True
                    break 
            
            if restart: 
                continue

            # Alle deltagere har svaret
            self.state.s = Status.NORMAL
            self.storage.atomic_update(self.state)
            self.processing = True
            return

    def check(self) -> None:
        # Kun én koordinator i normal
        if self.state.s != Status.NORMAL or self.state.c != self.id:
            return
        # Undersøg de andre noder
        for node_id in range(1, self.n+1):
            if node_id == self.id:
                continue

            normal = self.comm.query_normal(node_id)

            # En levende node er ikke normal
            if normal is False:
                self.election
                return


    def timeout(self) -> None:
        if self.state.s in (Status.NORMAL, Status.REORGANIZATION):
            coordinator_id = self.state.c

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
            
        

            








        
        