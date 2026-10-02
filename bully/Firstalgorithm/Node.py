from enum import Enum, auto

class Status(Enum):
    DOWN = auto()
    NORMAL = auto()
    REORGANIZATION = auto()
    ELECTION = auto()

class Node: 
    def __init__(self, node_id: int):
        self.id = node_id # Nodens id
        self.s = Status.DOWN # initialiserer status - Down
        self.c : int | None = None # id - Koordinator 
        self.h : int | None = None # id - seneste node der sendte halt
        self.up: set[int] = set() #Set - Noder der svarede på halt
        self.d : str | None = None # Opgave angivelse
        self.processing = False # Initialiser arbejde

    def are_you_there(self) -> bool: # Undersøg om Noden er til stede(crashet node kan ikke modtage) 
        return True

    def are_you_normal(self) -> bool: # 
        return self.s == Status.NORMAL

    def stop_processing(self) -> None:
        self.processing = False

    def halt(self, sender_id: int) -> None:
        self.s = Status.ELECTION # Status - Election
        self.h = sender_id #Markér sender_id
        self.stop_processing() 

    def new_coordinator(self, sender_id: int) -> None:
        if(self.s == Status.ELECTION and self.h == sender_id): # Hvis Noden er i Election og h == sender_id 
            self.c = sender_id # Sæt koordinator til sender_id
            self.s = Status.REORGANIZATION #Sæt status til reorginization

    def ready(self, sender_id: int, task: str) -> None:
        if(self.s == Status.REORGANIZATION and self.c == sender_id): # Noden SKAL være i Reorginization og koordiantor skal være sat til sender_id
            self.d = task # Sæt task
            self.s = Status.NORMAL # Status = Normal
            self.processing = True # Igangværende arbejde 


    

    


        




    

    

    


    




    

    

