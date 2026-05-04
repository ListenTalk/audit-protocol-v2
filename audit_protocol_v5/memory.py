class Memory:

    def __init__(self):
        self.data = []

    def add(self, q, a):
        self.data.append((q, a))

    def search(self, q):
        return [a for x, a in self.data if q.lower() in x.lower()]
